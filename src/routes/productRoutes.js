const express = require('express');
const {
  getProducts,
  getProductById,
  createProduct,
  updateProduct,
  deleteProduct,
} = require('../controllers/productController');
const { protect, authorizeRoles } = require('../middleware/authMiddleware');

const router = express.Router();

router.get('/', getProducts);
router.get('/:id', getProductById);
router.post('/', protect, authorizeRoles('staff', 'owner'), createProduct);
router.put('/:id', protect, authorizeRoles('staff', 'owner'), updateProduct);
router.delete('/:id', protect, authorizeRoles('staff', 'owner'), deleteProduct);

module.exports = router;
