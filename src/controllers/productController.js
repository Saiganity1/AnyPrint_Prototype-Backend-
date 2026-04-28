const asyncHandler = require('../middleware/asyncHandler');
const Product = require('../models/Product');

const getProducts = asyncHandler(async (req, res) => {
  const products = await Product.find().sort({ createdAt: -1 });
  res.json(products);
});

const getProductById = asyncHandler(async (req, res) => {
  const product = await Product.findById(req.params.id);

  if (!product) {
    res.status(404);
    throw new Error('Product not found');
  }

  res.json(product);
});

const createProduct = asyncHandler(async (req, res) => {
  const { name, description, price, sizes = [], colors = [], stock, imageUrl } = req.body;

  if (!name || !description || price === undefined || !imageUrl) {
    res.status(400);
    throw new Error('Name, description, price, and imageUrl are required');
  }

  if (!Array.isArray(sizes) || !Array.isArray(colors)) {
    res.status(400);
    throw new Error('Sizes and colors must be arrays');
  }

  const product = await Product.create({
    name,
    description,
    price,
    sizes,
    colors,
    stock: stock ?? 0,
    imageUrl,
  });

  res.status(201).json(product);
});

const updateProduct = asyncHandler(async (req, res) => {
  const product = await Product.findByIdAndUpdate(req.params.id, req.body, {
    new: true,
    runValidators: true,
  });

  if (!product) {
    res.status(404);
    throw new Error('Product not found');
  }

  res.json(product);
});

const deleteProduct = asyncHandler(async (req, res) => {
  const product = await Product.findByIdAndDelete(req.params.id);

  if (!product) {
    res.status(404);
    throw new Error('Product not found');
  }

  res.json({ message: 'Product deleted successfully' });
});

module.exports = {
  getProducts,
  getProductById,
  createProduct,
  updateProduct,
  deleteProduct,
};
