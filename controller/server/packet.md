# Packet Schema

## State Packet

```json
{
    "type": "state",
    "agent": "model-name",
    "data": {
        "status": "current-model-status"
    }
}
```

## Round Packet

```json
{
    "type": "round",
    "agent": "model",
    "data": {
        "argument-count": {
            "current": "int",
            "total": "int"
        },

        "round": {
            "current": "int",
            "total": "int"
        }         
    }
}
```

## Error Packet

```json
{
    "type": "error",
    "agent": "model",
    "data": {
        "error": "error-message"
    }
}
```

## Response Packet

```json
{
    "type": "response",
    "agent": "model",
    "data": {
        "response": "response-message"
    }
}
```

## Complete Packet

```json
{
    "type": "complete",
    "agent": "model",
    "data": {
        "complete": "complete-message or bolean value ig"
    }
}
```

