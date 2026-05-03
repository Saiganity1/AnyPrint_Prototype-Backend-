const joi = require('joi');

const schemas = {
  // User registration validation
  registerUser: joi.object({
    name: joi.string().min(2).max(50).required().messages({
      'string.empty': 'Name is required',
      'string.min': 'Name must be at least 2 characters',
      'string.max': 'Name cannot exceed 50 characters',
    }),
    email: joi.string().email().required().messages({
      'string.email': 'Please provide a valid email address',
      'string.empty': 'Email is required',
    }),
    password: joi.string().min(8).max(100).required().messages({
      'string.min': 'Password must be at least 8 characters',
      'string.empty': 'Password is required',
    }),
  }),

  // User login validation
  loginUser: joi.object({
    email: joi.string().email().required().messages({
      'string.email': 'Please provide a valid email address',
      'string.empty': 'Email is required',
    }),
    password: joi.string().required().messages({
      'string.empty': 'Password is required',
    }),
  }),

  // Product creation/update validation
  createProduct: joi.object({
    name: joi.string().min(3).max(100).required().messages({
      'string.empty': 'Product name is required',
      'string.min': 'Product name must be at least 3 characters',
    }),
    description: joi.string().max(1000).optional(),
    price: joi.number().positive().required().messages({
      'number.positive': 'Price must be a positive number',
      'any.required': 'Price is required',
    }),
    category: joi.string().max(50).optional(),
    print_style: joi.string().max(50).optional(),
    sizes: joi.array().items(joi.string()).optional(),
    colors: joi.array().items(joi.string()).optional(),
  }),

  // Order creation validation
  createOrder: joi.object({
    items: joi.array().items(
      joi.object({
        product_id: joi.string().required(),
        quantity: joi.number().min(1).required(),
        size: joi.string().optional(),
        color: joi.string().optional(),
      })
    ).min(1).required().messages({
      'array.min': 'Order must contain at least one item',
    }),
    shipping_address: joi.object({
      street: joi.string().required(),
      city: joi.string().required(),
      postal_code: joi.string().required(),
      country: joi.string().required(),
    }).required(),
    payment_method: joi.string().valid('card', 'paypal', 'bank_transfer').required(),
  }),

  // Message validation
  createMessage: joi.object({
    recipient_id: joi.string().required(),
    content: joi.string().min(1).max(5000).required().messages({
      'string.empty': 'Message content is required',
      'string.max': 'Message cannot exceed 5000 characters',
    }),
  }),
};

// Validation middleware factory
const validate = (schema) => {
  return (req, res, next) => {
    const { error, value } = schema.validate(req.body, {
      abortEarly: false,
      stripUnknown: true,
    });

    if (error) {
      const messages = error.details.map(detail => detail.message);
      return res.status(400).json({
        error: 'Validation failed',
        details: messages,
      });
    }

    req.body = value;
    next();
  };
};

module.exports = {
  schemas,
  validate,
};
