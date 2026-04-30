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
  const { recipient_id, content } = req.body;
  const sender_id = req.user.id;
  const sender_role = normalizeRole(req.user.role);

  if (!recipient_id || !content || !content.trim()) {
    return res.status(400).json({ error: 'Recipient and message content are required' });
  }

  // Verify recipient exists
  const recipient = await User.findById(recipient_id);
  if (!recipient) {
    return res.status(404).json({ error: 'Recipient not found' });
  }

  if (sender_role === 'user') {
    if (!isManagerRole(recipient.role)) {
      return res.status(403).json({ error: 'Users can only message admin or owner accounts' });
    }
  } else if (isManagerRole(req.user.role)) {
    if (normalizeRole(recipient.role) !== 'user') {
      return res.status(403).json({ error: 'Managers can only reply to users' });
    }

    const existingConversation = await Message.exists({
      conversation_id: [sender_id.toString(), recipient_id.toString()].sort().join('_'),
    });

    if (!existingConversation) {
      return res.status(403).json({ error: 'Managers can only reply after a user starts the conversation' });
    }
  } else {
    return res.status(403).json({ error: 'Unsupported chat role' });
  }

  // Create conversation ID (consistent regardless of order)
  const conversation_id = [sender_id.toString(), recipient_id.toString()].sort().join('_');

  const message = await Message.create({
    conversation_id,
    sender_id,
    sender_name: req.user.name,
    sender_role: req.user.role,
    recipient_id,
    content: content.trim(),
  });

  const populatedMessage = await message.populate('sender_id', 'name email');

  // Emit via socket.io to the conversation room if available
  try {
    const socketModule = require('../socket');
    const ioInstance = socketModule.getIO();
    ioInstance.to(conversation_id).emit('new_message', populatedMessage);
  } catch (err) {
    // socket not initialized or other error: continue silently
  }

  res.status(201).json({
    success: true,
    message: populatedMessage,
  });
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
