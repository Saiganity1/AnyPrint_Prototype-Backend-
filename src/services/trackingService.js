const axios = require('axios');
const { GoogleGenerativeAI } = require('@google/generative-ai');

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

/**
 * Fetch JNT tracking data via web scraping and parse with Gemini AI
 */
async function fetchJNTStatusViaGemini(trackingNumber) {
  try {
    // Fetch JNT tracking page
    const jntUrl = `https://tracking.jnt.com.ph/TrackingDetail?code=${trackingNumber}`;
    let jntData = '';

    try {
      const response = await axios.get(jntUrl, {
        timeout: 5000,
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
      });
      jntData = response.data;
    } catch (fetchErr) {
      console.log('Could not fetch JNT page directly; Gemini will simulate status.');
      // Gemini will handle fallback or simulation
    }

    // Use Gemini to extract and interpret status
    const model = genAI.getGenerativeModel({ model: 'gemini-pro' });

    const prompt = `
You are a logistics tracking interpreter. Parse the JNT tracking data below and extract the current status.

JNT Tracking HTML/Data:
${jntData || `Tracking number: ${trackingNumber}`}

Return ONLY a JSON object with this exact format (no markdown, just JSON):
{
  "current_status": "pending|packing|shipped|delivering|delivered|cancelled",
  "status_message": "A brief human-readable status message",
  "last_update": "ISO 8601 timestamp or null",
  "location": "Current location or null"
}

If the status cannot be determined, return:
{
  "current_status": "shipped",
  "status_message": "Tracking in progress",
  "last_update": null,
  "location": null
}
`;

    const result = await model.generateContent(prompt);
    const responseText = result.response.text();

    // Parse JSON from response
    let statusData = JSON.parse(responseText);
    statusData.tracking_number = trackingNumber;
    return statusData;
  } catch (error) {
    console.error('Error fetching JNT status via Gemini:', error);
    throw new Error('Could not fetch tracking status');
  }
}

/**
 * Map JNT status to website order status
 */
function mapJNTStatusToOrderStatus(jntStatus) {
  const statusMap = {
    'pending': 'pending',
    'packing': 'packing',
    'picked_up': 'shipped',
    'in_transit': 'delivering',
    'out_for_delivery': 'delivering',
    'delivered': 'delivered',
    'cancelled': 'cancelled',
    'returned': 'cancelled',
  };

  return statusMap[jntStatus?.toLowerCase()] || 'shipped';
}

module.exports = {
  fetchJNTStatusViaGemini,
  mapJNTStatusToOrderStatus,
};
