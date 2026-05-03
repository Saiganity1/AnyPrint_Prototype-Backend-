/**
 * Rate limiting middleware for protecting endpoints
 */

const rateLimit = (options = {}) => {
  const {
    windowMs = 15 * 60 * 1000, // 15 minutes
    maxRequests = 100,
    message = 'Too many requests, please try again later.',
    skipSuccessfulRequests = false,
    skipFailedRequests = false,
  } = options;

  const stores = new Map();

  return (req, res, next) => {
    const key = req.ip || req.connection.remoteAddress;
    const now = Date.now();

    if (!stores.has(key)) {
      stores.set(key, { count: 0, resetTime: now + windowMs });
    }

    const record = stores.get(key);

    // Reset counter if window has passed
    if (now > record.resetTime) {
      record.count = 0;
      record.resetTime = now + windowMs;
    }

    record.count++;

    // Set headers
    res.setHeader('X-RateLimit-Limit', maxRequests);
    res.setHeader('X-RateLimit-Remaining', Math.max(0, maxRequests - record.count));
    res.setHeader('X-RateLimit-Reset', new Date(record.resetTime).toISOString());

    if (record.count > maxRequests) {
      res.status(429).json({ error: message });
      return;
    }

    next();
  };
};

/**
 * Specific rate limiters for different endpoints
 */
const createAuthLimiter = () => {
  return rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    maxRequests: 5, // Max 5 attempts
    message: 'Too many login attempts. Please try again after 15 minutes.',
  });
};

const createApiLimiter = () => {
  return rateLimit({
    windowMs: 60 * 1000, // 1 minute
    maxRequests: 30,
    message: 'API rate limit exceeded. Please try again later.',
  });
};

const createCreateLimiter = () => {
  return rateLimit({
    windowMs: 60 * 1000, // 1 minute
    maxRequests: 10,
    message: 'Too many requests. Please try again later.',
  });
};

module.exports = {
  rateLimit,
  createAuthLimiter,
  createApiLimiter,
  createCreateLimiter,
};
