import io from 'socket.io-client';

// Single shared Socket.IO connection to the J.A.R.V.I.S backend. Importing this
// everywhere (App.jsx, dashboard modules, ...) guarantees one connection and a
// consistent event stream instead of each module opening its own socket.
export const socket = io('http://localhost:8000');

export default socket;
