const express = require('express');
const { setTrackingNumber, checkAndUpdateStatus, checkAllOrdersStatus, getTrackingStatus } = require('../controllers/trackingController');
const authMiddleware = require('../middleware/authMiddleware');

const router = express.Router();

/**
 * Set tracking number for an order (admin/owner only)
 */
router.post('/set-tracking-number', authMiddleware, setTrackingNumber);

/**
 * Manually check and update order status via Gemini (admin/owner only)
 */
router.post('/check-status/:orderId', authMiddleware, checkAndUpdateStatus);

/**
 * Bulk check all active orders (admin/owner/cron only)
 */
router.post('/check-all-orders', authMiddleware, checkAllOrdersStatus);

/**
 * Get tracking status for an order
 */
router.get('/:orderId', authMiddleware, getTrackingStatus);

module.exports = router;
