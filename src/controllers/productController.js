const asyncHandler = require('../middleware/asyncHandler');
const Product = require('../models/Product');

const normalizeArrayField = (value, fallback = []) => {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }

  if (typeof value === 'string') {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  return fallback;
};

const fileToDataUrl = (file) => {
  if (!file) {
    return '';
  }

  return `data:${file.mimetype};base64,${file.buffer.toString('base64')}`;
};

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
  const { name, description, price, stock } = req.body;
  const sizes = normalizeArrayField(req.body.sizes);
  const colors = normalizeArrayField(req.body.colors);
  const imageUrl = fileToDataUrl(req.file) || String(req.body.imageUrl || '').trim();

  if (!name || !description || price === undefined || !imageUrl) {
    res.status(400);
    throw new Error('Name, description, price, and image are required');
  }

  const product = await Product.create({
    name,
    description,
    price: Number(price),
    sizes,
    colors,
    stock: Number(stock ?? 0),
    imageUrl,
  });

  res.status(201).json(product);
});

const updateProduct = asyncHandler(async (req, res) => {
  const update = { ...req.body };

  if (update.sizes !== undefined) {
    update.sizes = normalizeArrayField(update.sizes);
  }

  if (update.colors !== undefined) {
    update.colors = normalizeArrayField(update.colors);
  }

  if (update.price !== undefined) {
    update.price = Number(update.price);
  }

  if (update.stock !== undefined) {
    update.stock = Number(update.stock);
  }

  const uploadedImageUrl = fileToDataUrl(req.file);
  if (uploadedImageUrl) {
    update.imageUrl = uploadedImageUrl;
  }

  const product = await Product.findByIdAndUpdate(req.params.id, update, {
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
