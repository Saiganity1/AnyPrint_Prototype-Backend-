# Gemini AI Tracking Integration Setup Guide

## Overview
This implementation uses Google's Generative AI (Gemini) to automatically fetch and update order tracking status from JNT (Japan Network Transport) Philippines courier.

## How It Works

1. **Admin/Owner sets tracking number** on an order via `/admin/tracking` page
2. **Manual trigger**: Click "Check Status" button to immediately sync status
3. **Automatic polling**: Backend can periodically check all active orders (via cron job)
4. **Gemini AI fetches JNT data** and interprets shipping status
5. **Order status is automatically updated** on your website

## Setup Steps

### Step 1: Get Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API Key"** in a new project
3. Copy the API key

### Step 2: Update Backend Environment Variables

Add to your `.env` file in the backend:

```env
GEMINI_API_KEY=your_api_key_here
```

### Step 3: Install Gemini Package

Run in the backend directory:

```bash
npm install @google/generative-ai axios
```

### Step 4: Database Migration

Your Order model has been updated with these new fields:
- `tracking_number` - JNT tracking number
- `tracking_provider` - defaults to 'jnt'
- `tracking_status` - last known status message from JNT
- `ai_last_checked` - timestamp of last Gemini check

**NOTE**: If you have existing orders in the database, they'll still work, but won't have these fields populated until you explicitly set a tracking number.

### Step 5: Access Tracking Management

Admin/Owner users can now:
1. Go to `/admin/tracking` page
2. Search for orders
3. Click **"+ Add Tracking"** to input JNT tracking number
4. Click **"🔄 Check Status"** to manually sync with JNT
5. Click **"Check All Orders"** to sync all tracked orders

## API Endpoints

### Set Tracking Number
```
POST /api/tracking/set-tracking-number
Body: { orderId, tracking_number }
```

### Check Single Order Status
```
POST /api/tracking/check-status/:orderId
```

### Check All Orders (Bulk)
```
POST /api/tracking/check-all-orders
```

### Get Tracking Status
```
GET /api/tracking/:orderId
```

## Optional: Automatic Polling (Cron Job)

To automatically check all orders every hour, add this to your backend (e.g., in `server.js`):

```javascript
const cron = require('node-cron');

// Check all orders every hour
cron.schedule('0 * * * *', async () => {
  try {
    console.log('Running hourly tracking check...');
    await fetch(`${process.env.API_BASE || 'http://localhost:5000'}/api/tracking/check-all-orders`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.CRON_SECRET_TOKEN}`,
      },
    });
  } catch (err) {
    console.error('Cron tracking check failed:', err);
  }
});
```

And install: `npm install node-cron`

Then set `CRON_SECRET_TOKEN` in your `.env`.

## Status Mapping

JNT statuses are automatically mapped to your website statuses:

- **pending** → pending
- **packing** → packing
- **picked_up / in_transit** → shipped
- **out_for_delivery** → delivering
- **delivered** → delivered
- **cancelled / returned** → cancelled

## Troubleshooting

### Gemini Returns Error
- Verify your `GEMINI_API_KEY` is correct
- Check that your API key has access to `google.ai.generativelanguage.v1beta.GenerativeService`
- Try a simpler tracking number first

### JNT Tracking Not Found
- Verify the tracking number format (should be 8-10 digits)
- Check JNT's tracking website manually to confirm the number is valid

### Order Status Not Updating
- Click "Check Status" button manually first
- Check backend logs for any errors
- Verify order has a tracking number set

## Security Notes

- Tracking endpoints require authentication (admin/owner role)
- Never commit your `GEMINI_API_KEY` to version control
- Use environment variables for all sensitive data
- Consider rate-limiting Gemini API calls in production

## Future Enhancements

- Support for other couriers (Shopee, DHL, etc.)
- Webhook notifications when status changes
- Email alerts to customers on delivery
- Integration with SMS notifications
- Admin dashboard with tracking analytics
