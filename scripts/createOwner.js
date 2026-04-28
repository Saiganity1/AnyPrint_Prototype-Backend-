require('dotenv').config();

const connectDB = require('../src/config/db');
const User = require('../src/models/User');

const createOwner = async () => {
  const { OWNER_NAME, OWNER_EMAIL, OWNER_PASSWORD } = process.env;

  if (!OWNER_EMAIL || !OWNER_PASSWORD) {
    throw new Error('Set OWNER_EMAIL and OWNER_PASSWORD before running this script');
  }

  await connectDB();

  const existing = await User.findOne({ email: OWNER_EMAIL.toLowerCase() });
  if (existing) {
    existing.name = OWNER_NAME || existing.name;
    existing.role = 'owner';
    if (OWNER_PASSWORD) existing.password = OWNER_PASSWORD;
    await existing.save();
    console.log(`Updated owner account: ${existing.email}`);
    return;
  }

  const owner = await User.create({
    name: OWNER_NAME || 'AnyPrint Owner',
    email: OWNER_EMAIL,
    password: OWNER_PASSWORD,
    role: 'owner',
  });

  console.log(`Created owner account: ${owner.email}`);
};

createOwner()
  .catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  })
  .finally(async () => {
    const mongoose = require('mongoose');
    await mongoose.disconnect();
  });
