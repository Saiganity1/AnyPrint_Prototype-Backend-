/**
 * Optional: Auto-polling cron job for tracking updates
 * Add this to your server.js if you want automatic hourly checks
 * 
 * Install: npm install node-cron
 * Add to .env: CRON_SECRET_TOKEN=your-secret-token
 */

const cron = require('node-cron');
const { checkAllOrdersStatus } = require('../controllers/trackingController');

/**
 * Schedule tracking checks
 * Runs every hour at the top of the hour (0 minutes)
 */
function scheduleTrackingJobs() {
  // Every hour
  cron.schedule('0 * * * *', async () => {
    console.log('[Cron] Running hourly tracking check at', new Date().toISOString());
    try {
      // Create a mock request/response for the controller
      const mockReq = {};
      const mockRes = {
        json: (data) => {
          console.log('[Cron] Tracking check result:', data.message, `- ${data.results.length} orders processed`);
        },
      };

      // Call the controller directly
      await checkAllOrdersStatus(mockReq, mockRes);
    } catch (err) {
      console.error('[Cron] Tracking check failed:', err.message);
    }
  });

  console.log('[Cron] Tracking jobs scheduled successfully');

  // Optional: Run every 4 hours instead
  // cron.schedule('0 */4 * * *', async () => { ... });

  // Optional: Run every day at 2 AM
  // cron.schedule('0 2 * * *', async () => { ... });
}

module.exports = { scheduleTrackingJobs };
