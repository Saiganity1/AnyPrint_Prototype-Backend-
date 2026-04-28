const express = require('express');
const {
  getProducts,
  getProductById,
  createProduct,
  updateProduct,
  deleteProduct,
} = require('../controllers/productController');
const { protect, authorizeRoles } = require('../middleware/authMiddleware');
const upload = require('../middleware/uploadMiddleware');

const router = express.Router();

router.get('/', getProducts);
router.get('/:id', getProductById);
router.post('/', protect, authorizeRoles('admin', 'staff', 'owner'), upload.single('image'), createProduct);
router.put('/:id', protect, authorizeRoles('admin', 'staff', 'owner'), upload.single('image'), updateProduct);
router.delete('/:id', protect, authorizeRoles('admin', 'staff', 'owner'), deleteProduct);

module.exports = router;
