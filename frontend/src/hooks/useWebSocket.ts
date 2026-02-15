'use client'

import { useEffect, useRef, useState, useCallback } from 'react'

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api/ws/monitoring'

// Configuration constants
const MAX_MESSAGES = 500 // Maximum messages to store in memory

// Allowed message types for validation
const ALLOWED_MESSAGE_TYPES = [
  'agent_event',
  'agent_start',
  'agent_success',
  'agent_failure',
  'agent_timeout',
  'agent_retry',
  'workflow_complete',
  'initial_state',
  'system_update',
  'health_update',
  'heartbeat',
  'circuit_breaker',
  'alert',
  'metric',
  'error',
  'subscribe',
  'unsubscribe',
  'subscription_updated',
  'subscription_cleared',
  'filters_updated',
  'pong',
] as const

type AllowedMessageType = (typeof ALLOWED_MESSAGE_TYPES)[number]

// Type definitions for WebSocket messages
export interface WebSocketMessage {
  type: AllowedMessageType
  timestamp?: string
  agent_name?: string
  event_type?: string
  thread_id?: string
  status?: string
  step?: number
  execution_time?: number
  error?: string
  success?: boolean
  total_steps?: number
  data?: Record<string, unknown>
}

export interface SubscriptionFilters {
  agent_names?: string[]
  event_types?: string[]
  min_severity?: 'low' | 'medium' | 'high' | 'critical'
}

export interface UseWebSocketReturn {
  connected: boolean
  messages: WebSocketMessage[]
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error'
  sendMessage: (message: Record<string, unknown>) => void
  subscribe: (filters: SubscriptionFilters) => void
  unsubscribe: () => void
  clearMessages: () => void
}

// Reconnection configuration
const DEFAULT_RECONNECT_DELAY = 1000 // 1 second
const MAX_RECONNECT_DELAY = 30000 // 30 seconds
const RECONNECT_BACKOFF_MULTIPLIER = 1.5

/**
 * Type guard to check if a value is a valid string
 */
function isValidString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

/**
 * Type guard to check if a value is a valid number
 */
function isValidNumber(value: unknown): value is number {
  return typeof value === 'number' && !Number.isNaN(value) && Number.isFinite(value)
}

/**
 * Type guard to check if a value is a valid record/object
 */
function isValidRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Validates if a parsed message is a valid WebSocket message
 * Checks against allowed message types and required fields
 */
function isValidWebSocketMessage(data: unknown): data is WebSocketMessage {
  if (!isValidRecord(data)) {
    console.warn('[WebSocket] Invalid message: not an object')
    return false
  }

  // Check for required 'type' field
  if (!isValidString(data.type)) {
    console.warn('[WebSocket] Invalid message: missing or invalid "type" field')
    return false
  }

  // Validate against allowed message types
  if (!ALLOWED_MESSAGE_TYPES.includes(data.type as AllowedMessageType)) {
    console.warn(`[WebSocket] Invalid message type: "${data.type}". Allowed types:`, ALLOWED_MESSAGE_TYPES)
    return false
  }

  // Validate optional string fields if present
  if (data.timestamp !== undefined && !isValidString(data.timestamp)) {
    console.warn('[WebSocket] Invalid message: "timestamp" must be a string')
    return false
  }

  if (data.agent_name !== undefined && !isValidString(data.agent_name)) {
    console.warn('[WebSocket] Invalid message: "agent_name" must be a string')
    return false
  }

  if (data.event_type !== undefined && !isValidString(data.event_type)) {
    console.warn('[WebSocket] Invalid message: "event_type" must be a string')
    return false
  }

  if (data.thread_id !== undefined && !isValidString(data.thread_id)) {
    console.warn('[WebSocket] Invalid message: "thread_id" must be a string')
    return false
  }

  if (data.status !== undefined && !isValidString(data.status)) {
    console.warn('[WebSocket] Invalid message: "status" must be a string')
    return false
  }

  if (data.error !== undefined && !isValidString(data.error)) {
    console.warn('[WebSocket] Invalid message: "error" must be a string')
    return false
  }

  // Validate data if present
  if (data.data !== undefined && !isValidRecord(data.data)) {
    console.warn('[WebSocket] Invalid message: "data" must be an object')
    return false
  }

  return true
}

/**
 * Sanitizes agent name by checking against whitelist and removing dangerous characters
 */
export function sanitizeAgentName(agentName: unknown): string | null {
  if (!isValidString(agentName)) {
    return null
  }

  // Remove any potentially dangerous characters (HTML tags, scripts, etc.)
  const sanitized = agentName
    .replace(/<[^>]*>/g, '') // Remove HTML tags
    .replace(/javascript:/gi, '') // Remove javascript: protocol
    .replace(/on\w+=/gi, '') // Remove event handlers
    .trim()

  // Check if sanitization removed everything
  if (sanitized.length === 0) {
    return null
  }

  // Limit length to prevent abuse
  if (sanitized.length > 100) {
    console.warn(`[WebSocket] Agent name too long, truncating: ${sanitized.length} chars`)
    return sanitized.substring(0, 100)
  }

  return sanitized
}

/**
 * Adds a message to the state with circular buffer behavior
 * Drops oldest messages when MAX_MESSAGES is exceeded
 */
function addMessageWithCircularBuffer(
  currentMessages: WebSocketMessage[],
  newMessage: WebSocketMessage
): WebSocketMessage[] {
  if (currentMessages.length < MAX_MESSAGES) {
    return [...currentMessages, newMessage]
  }

  // Circular buffer: remove oldest message and add new one
  const [, ...rest] = currentMessages
  return [...rest, newMessage]
}

export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const [connected, setConnected] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected')
  const [messages, setMessages] = useState<WebSocketMessage[]>([])
  const [currentFilters, setCurrentFilters] = useState<SubscriptionFilters | null>(null)
  const reconnectDelayRef = useRef(DEFAULT_RECONNECT_DELAY)

  // Function to connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    setConnectionStatus('connecting')

    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setConnectionStatus('connected')
        reconnectDelayRef.current = DEFAULT_RECONNECT_DELAY

        // Re-subscribe to filters after reconnection
        if (currentFilters) {
          ws.send(JSON.stringify({
            type: 'subscribe',
            filters: currentFilters,
          }))
        }
      }

      ws.onmessage = (event) => {
        try {
          const parsedData = JSON.parse(event.data)

          // Validate message before processing
          if (!isValidWebSocketMessage(parsedData)) {
            return
          }

          const message: WebSocketMessage = parsedData

          // Apply filters if active
          if (currentFilters) {
            if (currentFilters.agent_names && message.agent_name) {
              if (!currentFilters.agent_names.includes(message.agent_name)) {
                return
              }
            }
            if (currentFilters.event_types && message.event_type) {
              if (!currentFilters.event_types.includes(message.event_type)) {
                return
              }
            }
          }

          // Add message with circular buffer to prevent unbounded growth
          setMessages((prev) => addMessageWithCircularBuffer(prev, message))
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error)
        }
      }

      ws.onclose = (event) => {
        setConnected(false)
        setConnectionStatus('disconnected')
        wsRef.current = null

        // Auto-reconnect with exponential backoff
        if (!event.wasClean) {
          const delay = reconnectDelayRef.current
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectDelayRef.current = Math.min(
              delay * RECONNECT_BACKOFF_MULTIPLIER,
              MAX_RECONNECT_DELAY
            )
            connect()
          }, delay)
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Connection error:', error)
        setConnectionStatus('error')
      }
    } catch (error) {
      console.error('[WebSocket] Failed to create connection:', error)
      setConnectionStatus('error')
    }
  }, [currentFilters])

  // Function to disconnect
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setConnected(false)
    setConnectionStatus('disconnected')
  }, [])

  // Function to send a message
  const sendMessage = useCallback((message: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    } else {
      console.warn('[WebSocket] Not connected. Message not sent:', message)
    }
  }, [])

  // Function to subscribe to filtered messages
  const subscribe = useCallback((filters: SubscriptionFilters) => {
    setCurrentFilters(filters)

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendMessage({
        type: 'subscribe',
        filters,
      })
    }
  }, [sendMessage])

  // Function to unsubscribe from filtered messages
  const unsubscribe = useCallback(() => {
    setCurrentFilters(null)

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendMessage({
        type: 'unsubscribe',
      })
    }
  }, [sendMessage])

  // Function to clear messages
  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])

  // Establish connection on mount
  useEffect(() => {
    connect()

    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  return {
    connected,
    messages,
    connectionStatus,
    sendMessage,
    subscribe,
    unsubscribe,
    clearMessages,
  }
}
