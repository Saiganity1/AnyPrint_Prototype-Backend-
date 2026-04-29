const express = require('express');
const { protect } = require('../middleware/authMiddleware');
const {
  sendMessage,
  getConversations,
  getMessages,
  getAdminChat,
  getUnreadCount,
  deleteMessage,
} = require('../controllers/chatController');

const router = express.Router();

// All routes require authentication
router.use(protect);

// Send a message
router.post('/send', sendMessage);

// Get all conversations for current user
router.get('/conversations', getConversations);

// Get messages for a specific conversation
router.get('/conversations/:conversation_id', getMessages);

// Get or create admin conversation
router.get('/admin', getAdminChat);

// Get unread message count
router.get('/unread', getUnreadCount);

// Delete a message
router.delete('/:message_id', deleteMessage);

module.exports = router;
