const express = require('express');
const { createOrder, getMyOrders, getAllOrders, updateOrder } = require('../controllers/orderController');
const { protect, authorizeRoles } = require('../middleware/authMiddleware');

const router = express.Router();

router.post('/', protect, authorizeRoles('user', 'owner'), createOrder);
router.get('/me', protect, authorizeRoles('user', 'owner'), getMyOrders);
router.get('/', protect, authorizeRoles('staff', 'owner'), getAllOrders);
router.put('/:id', protect, authorizeRoles('staff', 'owner'), updateOrder);

module.exports = router;
