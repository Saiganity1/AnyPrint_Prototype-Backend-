const mongoose = require('mongoose');
const asyncHandler = require('../middleware/asyncHandler');
const Order = require('../models/Order');
const Product = require('../models/Product');

const allowedStatuses = ['pending', 'paid', 'shipped', 'completed', 'cancelled'];

const populateOrder = (query) =>
  query.populate('userId', 'name email role').populate('items.productId', 'name price imageUrl');

const restoreStock = async (updatedProducts) => {
  await Promise.all(
    updatedProducts.map(({ productId, quantity }) =>
      Product.findByIdAndUpdate(productId, { $inc: { stock: quantity } })
    )
  );
};

const createOrder = asyncHandler(async (req, res) => {
  const { items } = req.body;

  if (!Array.isArray(items) || items.length === 0) {
    res.status(400);
    throw new Error('Order items are required');
  }

  const normalizedItems = [];
  const updatedProducts = [];
  let totalPrice = 0;

  try {
    for (const item of items) {
      const { productId, quantity, size, color } = item || {};

      if (!productId || quantity === undefined || !size || !color) {
        res.status(400);
        throw new Error('Each order item must include productId, quantity, size, and color');
      }

      if (!Number.isInteger(quantity) || quantity < 1) {
        res.status(400);
        throw new Error('Each order item quantity must be a positive whole number');
      }

      if (!mongoose.Types.ObjectId.isValid(productId)) {
        res.status(400);
        throw new Error('Invalid productId supplied in order items');
      }

      const existingProduct = await Product.findById(productId);

      if (!existingProduct) {
        res.status(404);
        throw new Error('One or more products were not found');
      }

      const product = await Product.findOneAndUpdate(
        { _id: productId, stock: { $gte: quantity } },
        { $inc: { stock: -quantity } },
        { new: true }
      );

      if (!product) {
        res.status(400);
        throw new Error(`Insufficient stock for ${existingProduct.name}`);
      }

      updatedProducts.push({ productId: product._id, quantity });
      normalizedItems.push({
        productId: product._id,
        quantity,
        size,
        color,
        unitPrice: product.price,
      });
      totalPrice += product.price * quantity;
    }

    const order = await Order.create({
      userId: req.user._id,
      items: normalizedItems,
      totalPrice,
    });

    const populatedOrder = await populateOrder(Order.findById(order._id));
    res.status(201).json(populatedOrder);
  } catch (error) {
    await restoreStock(updatedProducts);
    throw error;
  }
});

const getMyOrders = asyncHandler(async (req, res) => {
  const orders = await populateOrder(Order.find({ userId: req.user._id }).sort({ createdAt: -1 }));
  res.json(orders);
});

const getAllOrders = asyncHandler(async (req, res) => {
  const orders = await populateOrder(Order.find().sort({ createdAt: -1 }));
  res.json(orders);
});

const updateOrder = asyncHandler(async (req, res) => {
  const { status } = req.body;

  if (!status || !allowedStatuses.includes(status)) {
    res.status(400);
    throw new Error('A valid order status is required');
  }

  const order = await Order.findById(req.params.id);

  if (!order) {
    res.status(404);
    throw new Error('Order not found');
  }

  if (order.status === 'cancelled' && status !== 'cancelled') {
    res.status(400);
    throw new Error('Cancelled orders cannot be moved back to an active status');
  }

  if (status === 'cancelled' && order.status !== 'cancelled') {
    await Promise.all(
      order.items.map(async (item) => {
        const product = await Product.findById(item.productId);
        if (product) {
          product.stock += item.quantity;
          await product.save();
        }
      })
    );
  }

  order.status = status;
  await order.save();

  const populatedOrder = await populateOrder(Order.findById(order._id));
  res.json(populatedOrder);
});

module.exports = {
  createOrder,
  getMyOrders,
  getAllOrders,
  updateOrder,
};
