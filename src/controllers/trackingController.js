const asyncHandler = require('../middleware/asyncHandler');
const Order = require('../models/Order');
const { fetchJNTStatusViaGemini, mapJNTStatusToOrderStatus } = require('../services/trackingService');

/**
 * Update order tracking with a tracking number
 * POST /tracking/set-tracking-number
 */
const setTrackingNumber = asyncHandler(async (req, res) => {
  const { orderId, tracking_number } = req.body;

  if (!orderId || !tracking_number) {
    res.status(400);
    throw new Error('Order ID and tracking number are required');
  }

  const order = await Order.findById(orderId);
  if (!order) {
    res.status(404);
    throw new Error('Order not found');
  }

  order.tracking_number = tracking_number;
  await order.save();

  res.json({
    message: 'Tracking number set successfully',
    order,
  });
});

/**
 * Manually trigger Gemini AI to fetch and update order status
 * POST /tracking/check-status/:orderId
 */
const checkAndUpdateStatus = asyncHandler(async (req, res) => {
  const { orderId } = req.params;

  const order = await Order.findById(orderId);
  if (!order) {
    res.status(404);
    throw new Error('Order not found');
  }

  if (!order.tracking_number) {
    res.status(400);
    throw new Error('No tracking number set for this order');
  }

  // Fetch status via Gemini
  const trackingData = await fetchJNTStatusViaGemini(order.tracking_number);

  // Map status
  const newStatus = mapJNTStatusToOrderStatus(trackingData.current_status);

  // Update order
  order.status = newStatus;
  order.tracking_status = trackingData.status_message;
  order.ai_last_checked = new Date();
  await order.save();

  res.json({
    message: 'Order status updated',
    order,
    tracking_data: trackingData,
  });
});

/**
 * Bulk update all orders with tracking numbers
 * POST /tracking/check-all-orders
 * (Called by cron job for auto-polling)
 */
const checkAllOrdersStatus = asyncHandler(async (req, res) => {
  const orders = await Order.find({
    tracking_number: { $exists: true, $ne: null },
    status: { $ne: 'delivered', $ne: 'cancelled' },
  });

  const results = [];

  for (const order of orders) {
    try {
      const trackingData = await fetchJNTStatusViaGemini(order.tracking_number);
      const newStatus = mapJNTStatusToOrderStatus(trackingData.current_status);

      order.status = newStatus;
      order.tracking_status = trackingData.status_message;
      order.ai_last_checked = new Date();
      await order.save();

      results.push({
        orderId: order._id,
        status: 'success',
        new_status: newStatus,
      });
    } catch (err) {
      results.push({
        orderId: order._id,
        status: 'error',
        error: err.message,
      });
    }
  }

  res.json({
    message: `Checked ${orders.length} orders`,
    results,
  });
});

/**
 * Get tracking status for an order
 * GET /tracking/:orderId
 */
const getTrackingStatus = asyncHandler(async (req, res) => {
  const { orderId } = req.params;

  const order = await Order.findById(orderId);
  if (!order) {
    res.status(404);
    throw new Error('Order not found');
  }

  res.json({
    tracking_number: order.tracking_number,
    status: order.status,
    tracking_status: order.tracking_status,
    ai_last_checked: order.ai_last_checked,
  });
});

module.exports = {
  setTrackingNumber,
  checkAndUpdateStatus,
  checkAllOrdersStatus,
  getTrackingStatus,
};
