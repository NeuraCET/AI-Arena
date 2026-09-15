import { useState, useEffect, useRef, useCallback } from 'react';

type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';
type MessageType = 'state' | 'round' | 'error' | 'response' | 'complete';
type AgentType = 'model';

interface StateData {
  status: string;
}

interface RoundData {
  'argument-count': {
    current: number;
    total: number;
  };
  round: {
    current: number;
    total: number;
  };
}

interface ErrorData {
  error: string;
}

interface ResponseData {
  response: string;
}

interface CompleteData {
  complete: string | boolean;
}

type MessageData = StateData | RoundData | ErrorData | ResponseData | CompleteData;

interface WebSocketMessage {
  type: MessageType;
  agent: AgentType;
  data: MessageData;
}

interface WebSocketConnectionOptions {
  maxReconnectAttempts?: number;
  baseReconnectDelay?: number;
  maxReconnectDelay?: number;
  enableReconnect?: boolean;
  maxMessages?: number;
}

interface WebSocketConnectionReturn {
  connectionStatus: ConnectionState;
  messages: WebSocketMessage[];
  sendMessage: (message: WebSocketMessage) => void;
  lastError: string | null;
  connect: () => void;
  disconnect: () => void;
  clearMessages: () => void;
  clearError: () => void;
  isConnected: boolean;
}

// Runtime message validator
function isValidWebSocketMessage(msg: unknown): msg is WebSocketMessage {
  if (!msg || typeof msg !== 'object') {
    return false;
  }

  const message = msg as Record<string, unknown>;

  // Check required fields exist
  if (!('type' in message) || !('agent' in message) || !('data' in message)) {
    return false;
  }

  // Validate type is one of the allowed values
  const validTypes: MessageType[] = ['state', 'round', 'error', 'response', 'complete'];
  if (typeof message.type !== 'string' || !validTypes.includes(message.type as MessageType)) {
    return false;
  }

  // Validate agent is 'model'
  if (message.agent !== 'model') {
    return false;
  }

  // Validate data is an object
  if (!message.data || typeof message.data !== 'object') {
    return false;
  }

  return true;
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
    maxMessages = 100,
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<ConnectionState>('disconnected');
  const [messages, setMessages] = useState<WebSocketMessage[]>([]);
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
            setMessages((prev) => {
              const newMessages = [...prev, parsedMessage];
              // Keep only the latest maxMessages to prevent memory issues
              if (newMessages.length > maxMessages) {
                return newMessages.slice(-maxMessages);
              }
              return newMessages;
            });
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
  }, [url, enableReconnect, maxReconnectAttempts, baseReconnectDelay, maxReconnectDelay, maxMessages]);

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

  const clearMessages = useCallback(() => {
    setMessages([]);
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
    messages,
    sendMessage,
    lastError,
    connect,
    disconnect,
    clearMessages,
    clearError,
    isConnected: connectionStatus === 'connected',
  };
}
