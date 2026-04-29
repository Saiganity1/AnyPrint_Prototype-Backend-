let io = null;

module.exports = {
  init(server) {
    // lazy require to avoid circular imports during startup
    const { Server } = require('socket.io');
    io = new Server(server, {
      cors: {
        origin: [process.env.CLIENT_ORIGIN, 'http://localhost:5173', 'http://localhost:3000'],
        methods: ['GET', 'POST'],
        credentials: true,
      },
    });

    io.on('connection', (socket) => {
      socket.on('join', (room) => {
        if (room) socket.join(room);
      });

      socket.on('leave', (room) => {
        if (room) socket.leave(room);
      });

      socket.on('disconnect', () => {});
    });

    return io;
  },

  getIO() {
    if (!io) throw new Error('Socket.io not initialized');
    return io;
  },
};
