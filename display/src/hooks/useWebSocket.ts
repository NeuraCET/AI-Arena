import { useState, useEffect, useRef, useCallback } from 'react';

type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

type WebSocketMessage = Record<string, unknown>;

type WebSocketConnectionOptions = {
  maxReconnectAttempts?: number;
  baseReconnectDelay?: number;
  maxReconnectDelay?: number;
  enableReconnect?: boolean;
};

type WebSocketConnectionReturn = {
  connectionStatus: ConnectionState;
  message: string | null;
  sendMessage: (message: WebSocketMessage) => void;
  lastError: string | null;
  connect: () => void;
  disconnect: () => void;
  clearMessage: () => void;
  clearError: () => void;
  isConnected: boolean;
};

// Runtime message validator
function isValidWebSocketMessage(msg: unknown): msg is WebSocketMessage {
  return msg !== null && typeof msg === 'object';
}

export function useWebSocketConnection(
  url: string,
  options: WebSocketConnectionOptions = {}
): WebSocketConnectionReturn {
  const {
    maxReconnectAttempts = 5,
    baseReconnectDelay = 1000,
    maxReconnectDelay = 30000,
    enableReconnect = true,
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<ConnectionState>('disconnected');
  const [message, setMessage] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isMountedRef = useRef(true);
  const connectRef = useRef<(() => void) | null>(null);
  const manuallyClosedRef = useRef(false);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    if (!isMountedRef.current) {
      return;
    }

    if (!url || typeof url !== 'string') {
      setLastError('Invalid WebSocket URL');
      setConnectionStatus('error');
      return;
    }

    // Reset manual close flag when starting a new connection
    manuallyClosedRef.current = false;
    setConnectionStatus('connecting');
    setLastError(null);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMountedRef.current) return;
        setConnectionStatus('connected');
        reconnectAttemptsRef.current = 0;
        setLastError(null);
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          const parsedMessage = JSON.parse(event.data);
          if (isValidWebSocketMessage(parsedMessage)) {
            setMessage(event.data);
          } else {
            console.warn('Received message with invalid structure:', parsedMessage);
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      ws.onerror = () => {
        if (!isMountedRef.current) return;
        setConnectionStatus('error');
        setLastError('WebSocket error occurred');
      };

      ws.onclose = (event) => {
        if (!isMountedRef.current) return;
        setConnectionStatus('disconnected');
        wsRef.current = null;

        // Only reconnect if not manually closed and conditions are met
        if (
          !manuallyClosedRef.current &&
          event.code !== 1000 &&
          enableReconnect &&
          reconnectAttemptsRef.current < maxReconnectAttempts
        ) {
          reconnectAttemptsRef.current++;
          const delay = Math.min(
            baseReconnectDelay * Math.pow(2, reconnectAttemptsRef.current) + Math.random() * 1000,
            maxReconnectDelay
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            if (isMountedRef.current && wsRef.current?.readyState !== WebSocket.OPEN && connectRef.current) {
              connectRef.current();
            }
          }, delay);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setLastError('Max reconnection attempts reached. Server may be down.');
        }
      };
    } catch (error) {
      if (!isMountedRef.current) return;
      setConnectionStatus('error');
      setLastError(error instanceof Error ? error.message : 'Failed to create WebSocket connection');
    }
  }, [url, enableReconnect, maxReconnectAttempts, baseReconnectDelay, maxReconnectDelay]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    manuallyClosedRef.current = true;
    cleanup();
    setConnectionStatus('disconnected');
  }, [cleanup]);

  const clearMessage = useCallback(() => {
    setMessage(null);
  }, []);

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify(message));
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Failed to send message';
        setLastError(errorMessage);
        console.error('WebSocket send error:', error);
      }
    } else {
      const errorMessage = 'WebSocket is not connected';
      setLastError(errorMessage);
      console.warn(errorMessage);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    connect();

    return () => {
      isMountedRef.current = false;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    connectionStatus,
    message,
    sendMessage,
    lastError,
    connect,
    disconnect,
    clearMessage,
    clearError,
    isConnected: connectionStatus === 'connected',
  };
}
