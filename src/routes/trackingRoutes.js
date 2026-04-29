const express = require('express');
const { setTrackingNumber, checkAndUpdateStatus, checkAllOrdersStatus, getTrackingStatus } = require('../controllers/trackingController');
const { protect } = require('../middleware/authMiddleware');

const router = express.Router();

/**
 * Set tracking number for an order (admin/owner only)
 */
router.post('/set-tracking-number', protect, setTrackingNumber);

/**
 * Manually check and update order status via Gemini (admin/owner only)
 */
router.post('/check-status/:orderId', protect, checkAndUpdateStatus);

/**
 * Bulk check all active orders (admin/owner/cron only)
 */
router.post('/check-all-orders', protect, checkAllOrdersStatus);

/**
 * Get tracking status for an order
 */
router.get('/:orderId', protect, getTrackingStatus);

module.exports = router;
