let io = null;

const isAllowedOrigin = (origin) => {
  if (!origin) return true;

  if (/^https:\/\/.*\.onrender\.com$/i.test(origin)) {
    return true;
  }

  if (/^https:\/\/.*\.netlify\.app$/i.test(origin)) {
    return true;
  }

  if (/^https:\/\/.*\.vercel\.app$/i.test(origin)) {
    return true;
  }

  if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(origin)) {
    return true;
  }

  const allowedOrigins = [
    process.env.CLIENT_ORIGIN,
    'http://localhost:5173',
    'http://localhost:3000',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:3000',
  ];

  return allowedOrigins.some((allowed) => allowed && allowed === origin);
};

module.exports = {
  init(server) {
    // lazy require to avoid circular imports during startup
    const { Server } = require('socket.io');
    io = new Server(server, {
      cors: {
        origin: isAllowedOrigin,
        methods: ['GET', 'POST'],
        credentials: true,
      },
    });

    io.on('connection', (socket) => {
      console.log(`[Socket.IO Backend] Client connected: ${socket.id}`);
      
      socket.on('join', (room) => {
        if (room) {
          socket.join(room);
          const roomSockets = io.sockets.adapter.rooms.get(room);
          console.log(`[Socket.IO Backend] Socket ${socket.id} joined room: ${room} (total in room: ${roomSockets ? roomSockets.size : 0})`);
        }
      });

      socket.on('leave', (room) => {
        if (room) {
          socket.leave(room);
          console.log(`[Socket.IO Backend] Socket ${socket.id} left room: ${room}`);
        }
      });

      socket.on('disconnect', () => {
        console.log(`[Socket.IO Backend] Client disconnected: ${socket.id}`);
      });

      socket.on('error', (err) => {
        console.error(`[Socket.IO Backend] Error for ${socket.id}:`, err);
      });
    });

    return io;
  },

  getIO() {
    if (!io) throw new Error('Socket.io not initialized');
    return io;
  },
};
