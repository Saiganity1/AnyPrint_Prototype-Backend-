require('dotenv').config();

const connectDB = require('../src/config/db');
const Product = require('../src/models/Product');

const products = [
  {
    name: 'Classic AnyPrint Tee',
    description: 'Soft cotton shirt for everyday custom prints.',
    price: 399,
    sizes: ['S', 'M', 'L', 'XL'],
    colors: ['Black', 'White', 'Navy'],
    stock: 30,
    imageUrl: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=900&q=80',
  },
  {
    name: 'Street Graphic Tee',
    description: 'Premium streetwear cut with bold print-ready fabric.',
    price: 549,
    sizes: ['M', 'L', 'XL'],
    colors: ['Black', 'Gray'],
    stock: 20,
    imageUrl: 'https://images.unsplash.com/photo-1503341504253-dff4815485f1?auto=format&fit=crop&w=900&q=80',
  },
  {
    name: 'Minimal Logo Tee',
    description: 'Clean minimal shirt for brand, school, and event designs.',
    price: 449,
    sizes: ['S', 'M', 'L'],
    colors: ['White', 'Beige', 'Black'],
    stock: 25,
    imageUrl: 'https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?auto=format&fit=crop&w=900&q=80',
  },
];

const seedProducts = async () => {
  await connectDB();

  for (const item of products) {
    const existing = await Product.findOne({ name: item.name });
    if (existing) {
      await Product.updateOne({ _id: existing._id }, item);
      console.log(`Updated product: ${item.name}`);
    } else {
      await Product.create(item);
      console.log(`Created product: ${item.name}`);
    }
  }
};

seedProducts()
  .catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  })
  .finally(async () => {
    const mongoose = require('mongoose');
    await mongoose.disconnect();
  });
