const express = require('express');
const compression = require('compression');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const cron = require('node-cron');
require('dotenv').config();

const connectDB = require('./src/config/db');
const authRoutes = require('./src/routes/authRoutes');
const productRoutes = require('./src/routes/productRoutes');
const orderRoutes = require('./src/routes/orderRoutes');
const trackingRoutes = require('./src/routes/trackingRoutes');
const chatRoutes = require('./src/routes/chatRoutes');
const seedAccounts = require('./scripts/seedAccounts');
const { notFound, errorHandler } = require('./src/middleware/errorMiddleware');
const Order = require('./src/models/Order');
const { fetchJNTStatusViaGemini, mapJNTStatusToOrderStatus } = require('./src/services/trackingService');

const app = express();
const http = require('http');
const PORT = process.env.PORT || 5000;

const allowedOrigins = new Set(
  [
    process.env.CLIENT_ORIGIN,
    'http://localhost:3000',
    'http://localhost:5173',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:5173',
    'https://anyprint-frontend.onrender.com',
    'https://anyprint-prototype.onrender.com',
  ]
    .flatMap((origin) => String(origin || '').split(','))
    .map((origin) => origin.trim())
    .filter(Boolean)
);

const isAllowedOrigin = (origin) => {
  if (!origin) {
    return true;
  }

  if (allowedOrigins.has(origin)) {
    return true;
  }

  if (/^https:\/\/.*\.onrender\.com$/i.test(origin)) {
    return true;
  }

  if (/^https:\/\/.*\.netlify\.app$/i.test(origin)) {
    return true;
  }

  if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(origin)) {
    return true;
  }

  return false;
};

const requiredEnv = ['JWT_SECRET'];
const missingEnv = requiredEnv.filter((key) => !process.env[key]);

if (missingEnv.length > 0) {
  throw new Error(`Missing required environment variables: ${missingEnv.join(', ')}`);
}

app.use(helmet());
// gzip compression for responses
app.use(compression());
app.use(
  cors({
    origin(origin, callback) {
      if (isAllowedOrigin(origin)) {
        callback(null, true);
        return;
      }

      callback(new Error(`CORS origin not allowed: ${origin}`));
    },
    credentials: true,
  })
);
app.use(express.json({ limit: '1mb' }));

if (process.env.NODE_ENV !== 'production') {
  app.use(morgan('dev'));
}

app.get('/api/health', (req, res) => {
  res.json({ success: true, message: 'AnyPrint Avenue API is running' });
});

app.use('/api/auth', authRoutes);
app.use('/api/products', productRoutes);
app.use('/api/orders', orderRoutes);
app.use('/api/tracking', trackingRoutes);
app.use('/api/chat', chatRoutes);

app.use(notFound);
app.use(errorHandler);

/**
 * Automatic tracking status check via Gemini AI
 * Runs every hour to check all orders with JNT tracking numbers
 */
async function scheduleAutomaticTrackingUpdates() {
  console.log('📅 Scheduling automatic JNT tracking updates (every hour)...');

  cron.schedule('0 * * * *', async () => {
    console.log(`[Cron] Running automatic tracking check at ${new Date().toISOString()}`);

    try {
      const orders = await Order.find({
        tracking_number: { $exists: true, $ne: null },
        status: { $nin: ['delivered', 'cancelled', 'rate'] },
      });

      if (orders.length === 0) {
        console.log('[Cron] No active orders with tracking numbers to check');
        return;
      }

      let updated = 0;
      let failed = 0;

      for (const order of orders) {
        try {
          const trackingData = await fetchJNTStatusViaGemini(order.tracking_number);
          const newStatus = mapJNTStatusToOrderStatus(trackingData.current_status);

          order.status = newStatus;
          order.tracking_status = trackingData.status_message;
          order.ai_last_checked = new Date();
          await order.save();

          console.log(`[Cron] ✓ Order ${order._id}: updated to '${newStatus}'`);
          updated++;
        } catch (err) {
          console.error(`[Cron] ✗ Order ${order._id}: ${err.message}`);
          failed++;
        }
      }

      console.log(
        `[Cron] Tracking check complete: ${updated} updated, ${failed} failed out of ${orders.length} orders`
      );
    } catch (err) {
      console.error('[Cron] Automatic tracking check failed:', err.message);
    }
  });
}

const startServer = async () => {
  try {
    await connectDB();
    await seedAccounts();

    // Schedule automatic tracking updates
    await scheduleAutomaticTrackingUpdates();

    const server = http.createServer(app);

    // Initialize socket.io
    try {
      const socket = require('./src/socket');
      socket.init(server);
      console.log('Socket.IO initialized');
    } catch (err) {
      console.warn('Socket.IO initialization failed:', err.message);
    }

    server.listen(PORT, () => {
      console.log(`Server running on port ${PORT}`);
    });
  } catch (error) {
    console.error('Failed to start server:', error.message);
    process.exit(1);
  }
};

startServer();
