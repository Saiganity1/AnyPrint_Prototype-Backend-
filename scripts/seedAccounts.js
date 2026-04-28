require('dotenv').config();

const connectDB = require('../src/config/db');
const User = require('../src/models/User');

const accounts = [
  {
    name: process.env.OWNER_NAME || 'Owner',
    email: process.env.OWNER_EMAIL || 'Owner@gmail.com',
    password: process.env.OWNER_PASSWORD || 'Owner1',
    role: 'owner',
  },
  {
    name: process.env.ADMIN_NAME || 'Admin',
    email: process.env.ADMIN_EMAIL || 'Admin@gmail.com',
    password: process.env.ADMIN_PASSWORD || 'Admin1',
    role: 'admin',
  },
];

const upsertAccount = async ({ name, email, password, role }) => {
  const normalizedEmail = email.toLowerCase();
  const existing = await User.findOne({ email: normalizedEmail });

  if (existing) {
    console.log(`${role} account already exists: ${existing.email}`);
    return;
  }

  const user = await User.create({
    name,
    email: normalizedEmail,
    password,
    role,
  });

  console.log(`Created ${role} account: ${user.email}`);
};

const seedAccounts = async () => {
  for (const account of accounts) {
    await upsertAccount(account);
  }
};

if (require.main === module) {
  connectDB()
    .then(seedAccounts)
    .catch((error) => {
      console.error(error.message);
      process.exitCode = 1;
    })
    .finally(async () => {
      const mongoose = require('mongoose');
      await mongoose.disconnect();
    });
}

module.exports = seedAccounts;