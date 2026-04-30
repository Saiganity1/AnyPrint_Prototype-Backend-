const asyncHandler = require('../middleware/asyncHandler');
const Message = require('../models/Message');
const User = require('../models/User');
let io;
try {
  io = require('../socket').getIO;
} catch (e) {
  // socket may not be initialized at import time
  io = null;
}

const MANAGER_ROLES = new Set(['admin', 'owner', 'staff']);

function normalizeRole(role) {
  return String(role || '').toLowerCase();
}

function isManagerRole(role) {
  return MANAGER_ROLES.has(normalizeRole(role));
}

// Send a message
exports.sendMessage = asyncHandler(async (req, res) => {
  try {
    console.log('\n[Chat sendMessage] ========== START ==========');
    console.log('[Chat sendMessage] req.body:', req.body);
    console.log('[Chat sendMessage] req.user:', req.user ? { id: req.user.id, role: req.user.role, name: req.user.name } : 'NOT AUTHENTICATED');

    const { recipient_id, content } = req.body;

    if (!req.user) {
      console.error('[Chat sendMessage] ERROR: User not authenticated');
      return res.status(401).json({ error: 'Not authenticated - missing user' });
    }

    if (!recipient_id || !content || !content.trim()) {
      console.error('[Chat sendMessage] ERROR: Missing recipient_id or content');
      return res.status(400).json({ error: 'Recipient and message content are required' });
    }

    const sender_id = req.user.id;
    const sender_role = normalizeRole(req.user.role);
    
    console.log('[Chat sendMessage] sender_id:', sender_id, 'role:', sender_role);

    // Verify recipient exists
    console.log('[Chat sendMessage] Finding recipient:', recipient_id);
    const recipient = await User.findById(recipient_id);
    if (!recipient) {
      console.error('[Chat sendMessage] ERROR: Recipient not found');
      return res.status(404).json({ error: 'Recipient not found' });
    }
    console.log('[Chat sendMessage] Recipient found:', recipient.name, recipient.role);

    // Find the primary admin
    console.log('[Chat sendMessage] Finding primary admin...');
    let primaryAdmin = await User.findOne({ role: 'owner' });
    if (!primaryAdmin) {
      primaryAdmin = await User.findOne({ role: 'admin' });
    }
    console.log('[Chat sendMessage] Primary admin:', primaryAdmin ? primaryAdmin.name : 'NOT FOUND');

    // Validate permissions
    if (sender_role === 'user') {
      if (!primaryAdmin || recipient_id.toString() !== primaryAdmin._id.toString()) {
        console.error('[Chat sendMessage] ERROR: User trying to message non-admin. Recipient:', recipient_id, 'Admin:', primaryAdmin?._id);
        return res.status(403).json({ error: 'You can only message the shop admin' });
      }
    } else if (isManagerRole(req.user.role)) {
      if (normalizeRole(recipient.role) !== 'user') {
        console.error('[Chat sendMessage] ERROR: Manager trying to message non-user');
        return res.status(403).json({ error: 'Managers can only chat with users' });
      }

      const existingConversation = await Message.exists({
        conversation_id: [sender_id.toString(), recipient_id.toString()].sort().join('_'),
      });

      if (!existingConversation) {
        console.error('[Chat sendMessage] ERROR: Manager replying to non-existent conversation');
        return res.status(403).json({ error: 'Managers can only reply after a user starts the conversation' });
      }
    } else {
      console.error('[Chat sendMessage] ERROR: Unsupported role:', sender_role);
      return res.status(403).json({ error: 'Unsupported chat role' });
    }

    // Create message
    const conversation_id = [sender_id.toString(), recipient_id.toString()].sort().join('_');
    console.log('[Chat sendMessage] Creating message in conversation:', conversation_id);

    const message = await Message.create({
      conversation_id,
      sender_id,
      sender_name: req.user.name,
      sender_role: req.user.role,
      recipient_id,
      content: content.trim(),
    });
    console.log('[Chat sendMessage] Message created:', message._id);

    const populatedMessage = await message.populate('sender_id', 'name email');
    const messageJson = populatedMessage.toJSON();
    console.log('[Chat sendMessage] Message populated successfully');

    // Emit via socket.io
    try {
      const socketModule = require('../socket');
      const ioInstance = socketModule.getIO();
      ioInstance.to(conversation_id).emit('new_message', messageJson);
      console.log(`[Chat sendMessage] Socket.IO emitted to room ${conversation_id}`);
    } catch (err) {
      console.warn(`[Chat sendMessage] Socket.IO emit failed: ${err.message}`);
    }

    console.log('[Chat sendMessage] ========== SUCCESS ==========\n');

    res.status(201).json({
      success: true,
      message: messageJson,
    });
  } catch (error) {
    console.error('[Chat sendMessage] ========== CAUGHT ERROR ==========');
    console.error('[Chat sendMessage] Error:', error.message);
    console.error('[Chat sendMessage] Stack:', error.stack);
    console.error('[Chat sendMessage] ========== END ERROR ==========\n');
    throw error; // Let asyncHandler pass to error middleware
  }
});

// Get all conversations for the current user
exports.getConversations = asyncHandler(async (req, res) => {
  const user_id = req.user.id;

  // Find all unique conversations involving this user
  const messages = await Message.find({
    $or: [{ sender_id: user_id }, { recipient_id: user_id }],
  })
    .populate('sender_id', 'name email role')
    .populate('recipient_id', 'name email role')
    .sort({ createdAt: -1 })
    .select('conversation_id sender_id recipient_id sender_name content createdAt read');

  // Group by conversation and get latest message
  const conversationsMap = new Map();

  messages.forEach((msg) => {
    if (!conversationsMap.has(msg.conversation_id)) {
      const otherUser = msg.sender_id._id.toString() === user_id ? msg.recipient_id : msg.sender_id;
      conversationsMap.set(msg.conversation_id, {
        conversation_id: msg.conversation_id,
        other_user: {
          id: otherUser._id,
          name: otherUser.name,
          email: otherUser.email,
          role: otherUser.role,
        },
        last_message: msg.content,
        last_message_at: msg.createdAt,
        unread_count: 0,
      });
    }

    // Count unread messages
    if (msg.recipient_id.toString() === user_id && !msg.read) {
      conversationsMap.get(msg.conversation_id).unread_count += 1;
    }
  });

  const conversations = Array.from(conversationsMap.values());

  res.json({
    success: true,
    conversations,
  });
});

// Get messages for a specific conversation
exports.getMessages = asyncHandler(async (req, res) => {
  const { conversation_id } = req.params;
  const user_id = req.user.id;
  const { limit = 50, offset = 0 } = req.query;

  // Verify user is part of this conversation
  const conversationExists = await Message.findOne({ conversation_id });
  if (!conversationExists) {
    return res.status(404).json({ error: 'Conversation not found' });
  }

  const messages = await Message.find({ conversation_id })
    .populate('sender_id', 'name email role')
    .populate('recipient_id', 'name email role')
    .sort({ createdAt: -1 })
    .limit(parseInt(limit))
    .skip(parseInt(offset));

  // Mark messages as read if recipient is viewing
  await Message.updateMany(
    {
      conversation_id,
      recipient_id: user_id,
      read: false,
    },
    {
      read: true,
      read_at: new Date(),
    }
  );

  res.json({
    success: true,
    messages: messages.reverse(),
    total: await Message.countDocuments({ conversation_id }),
  });
});

// Get or create admin conversation for user
exports.getAdminChat = asyncHandler(async (req, res) => {
  const user_id = req.user.id;

  // Find admin user (prefer 'owner', then 'admin')
  let admin = await User.findOne({ role: 'owner' });
  if (!admin) {
    admin = await User.findOne({ role: 'admin' });
  }

  if (!admin) {
    return res.status(404).json({ error: 'No admin user available for chat' });
  }

  const conversation_id = [user_id.toString(), admin._id.toString()].sort().join('_');

  res.json({
    success: true,
    conversation_id,
    admin: {
      id: admin._id,
      name: admin.name,
      email: admin.email,
      role: admin.role,
    },
  });
});

// Get unread message count
exports.getUnreadCount = asyncHandler(async (req, res) => {
  const user_id = req.user.id;

  const unreadCount = await Message.countDocuments({
    recipient_id: user_id,
    read: false,
  });

  res.json({
    success: true,
    unread_count: unreadCount,
  });
});

// Delete a message (only by sender)
exports.deleteMessage = asyncHandler(async (req, res) => {
  const { message_id } = req.params;
  const user_id = req.user.id;

  const message = await Message.findById(message_id);

  if (!message) {
    return res.status(404).json({ error: 'Message not found' });
  }

  if (message.sender_id.toString() !== user_id) {
    return res.status(403).json({ error: 'You can only delete your own messages' });
  }

  await Message.findByIdAndDelete(message_id);

  res.json({
    success: true,
    message: 'Message deleted successfully',
  });
});
