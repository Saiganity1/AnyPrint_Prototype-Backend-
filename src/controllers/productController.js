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

const fileListToDataUrls = (files = []) => files.map(fileToDataUrl).filter(Boolean);

const parseJsonField = (value, fallback = null) => {
  if (Array.isArray(value)) {
    return value;
  }

  if (typeof value === 'string' && value.trim()) {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }

  return fallback;
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
  const variantsInput = parseJsonField(req.body.variants, []);
  const variants = Array.isArray(variantsInput)
    ? variantsInput
        .map((variant) => ({
          size: String(variant?.size || '').trim(),
          color: String(variant?.color || '').trim(),
          stock: Number(variant?.stock || 0),
        }))
        .filter((variant) => variant.size || variant.color)
    : [];
  const uploadedImages = fileListToDataUrls(req.files || []);
  const fallbackImageUrl = fileToDataUrl(req.file) || String(req.body.imageUrl || '').trim();
  const images = uploadedImages.length ? uploadedImages : fallbackImageUrl ? [fallbackImageUrl] : [];
  const imageUrl = images[0] || fallbackImageUrl;
  const totalVariantStock = variants.reduce((sum, variant) => sum + Number(variant.stock || 0), 0);
  const totalStock = variants.length ? totalVariantStock : Number(stock ?? 0);
  const resolvedSizes = sizes.length ? sizes : [...new Set(variants.map((variant) => variant.size).filter(Boolean))];
  const resolvedColors = colors.length ? colors : [...new Set(variants.map((variant) => variant.color).filter(Boolean))];

  if (!name || !description || price === undefined || !imageUrl) {
    res.status(400);
    throw new Error('Name, description, price, and image are required');
  }

  const product = await Product.create({
    name,
    description,
    price: Number(price),
    sizes: resolvedSizes,
    colors: resolvedColors,
    variants,
    stock: totalStock,
    imageUrl,
    images,
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

  if (update.variants !== undefined) {
    const parsedVariants = parseJsonField(update.variants, []);
    update.variants = Array.isArray(parsedVariants)
      ? parsedVariants
          .map((variant) => ({
            size: String(variant?.size || '').trim(),
            color: String(variant?.color || '').trim(),
            stock: Number(variant?.stock || 0),
          }))
          .filter((variant) => variant.size || variant.color)
      : [];
    if (update.stock === undefined) {
      update.stock = update.variants.reduce((sum, variant) => sum + Number(variant.stock || 0), 0);
    }
  }

  const uploadedImages = fileListToDataUrls(req.files || []);
  if (uploadedImages.length) {
    update.images = uploadedImages;
    update.imageUrl = uploadedImages[0];
  } else {
    const uploadedImageUrl = fileToDataUrl(req.file);
    if (uploadedImageUrl) {
      update.imageUrl = uploadedImageUrl;
      update.images = [uploadedImageUrl];
    }
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
