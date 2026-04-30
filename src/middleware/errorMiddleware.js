const notFound = (req, res, next) => {
  const error = new Error(`Not Found - ${req.originalUrl}`);
  res.status(404);
  next(error);
};

const errorHandler = (err, req, res, next) => {
  const statusCode = res.statusCode === 200 ? 500 : res.statusCode;
  const response = {
    message: err.message || 'Internal Server Error',
  };

  // Log all errors to console for debugging
  console.error(`[ERROR] ${statusCode} - ${err.message}`);
  console.error('[ERROR] Stack:', err.stack);

  if (err.name === 'CastError') {
    res.status(404);
    response.message = 'Resource not found';
  } else if (err.name === 'ValidationError') {
    res.status(400);
    response.message = err.message;
  } else if (err.code === 11000) {
    res.status(400);
    response.message = 'Duplicate field value entered';
  } else if (err.name === 'JsonWebTokenError') {
    res.status(401);
    response.message = 'Invalid token';
  } else if (err.name === 'TokenExpiredError') {
    res.status(401);
    response.message = 'Token expired';
  } else {
    res.status(statusCode);
  }

  res.json(response);
};

module.exports = {
  notFound,
  errorHandler,
};
