# Call Transfer Guide

Complete guide for transferring active calls to human agents.

---

## How It Works

```
Call Active (Bot ↔ User)
    ↓
You trigger transfer (API call)
    ↓
Vobiz requests XML from /transfer-to-human
    ↓
Bot stops, call connects to human agent
    ↓
User ↔ Human Agent
```

---

## Quick Start

### Step 1: Make a Call

```bash
curl -X POST https://api.vobiz.ai/api/v1/Account/MA_SYQRLN1K/Call/ \
  -H "X-Auth-ID: MA_SYQRLN1K" \
  -H "X-Auth-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+918071387428",
    "to": "+919148227303",
    "answer_url": "https://your-ngrok-url.ngrok-free.app/answer",
    "answer_method": "POST"
  }'
```

**Response includes `call_uuid`** - save this!

```json
{
  "call_uuid": "abc-123-def-456",
  "message": "call fired"
}
```

### Step 2: List Active Calls (Optional)

```bash
curl http://localhost:7860/active-calls
```

**Response:**
```json
{
  "active_calls": ["abc-123-def-456"],
  "count": 1,
  "calls": {
    "abc-123-def-456": {
      "status": "active",
      "started_at": "2025-11-19T10:30:45",
      "path": "/ws"
    }
  }
}
```

### Step 3: Transfer the Call (While Active)

```bash
curl -X POST http://localhost:7860/initiate-transfer \
  -H "Content-Type: application/json" \
  -d '{
    "call_uuid": "abc-123-def-456"
  }'
```

**Response:**
```json
{
  "status": "transfer_initiated",
  "call_uuid": "abc-123-def-456",
  "transfer_url": "https://your-ngrok-url.ngrok-free.app/transfer-to-human",
  "vobiz_response": {
    "api_id": "xyz-789",
    "message": "call transferred"
  }
}
```

### What Happens:

1. Bot stops talking
2. User hears: "Please hold while I transfer you to a human agent"
3. Call connects to `+919148227303` (configured agent number)
4. User now talks to human agent

---

## Configuration

### Change Transfer Destination

**Option 1: Environment Variable (Recommended)**

Add to `.env`:
```env
TRANSFER_AGENT_NUMBER=+911234567890
```

**Option 2: Dynamic (Pass in Request)**

Modify `/initiate-transfer` to accept destination number:
```bash
curl -X POST http://localhost:7860/initiate-transfer \
  -H "Content-Type: application/json" \
  -d '{
    "call_uuid": "abc-123-def-456",
    "agent_number": "+911234567890"
  }'
```

---

## API Endpoints

### POST /initiate-transfer
Trigger call transfer to human agent

**Request:**
```json
{
  "call_uuid": "abc-123-def-456"
}
```

**Response (Success):**
```json
{
  "status": "transfer_initiated",
  "call_uuid": "abc-123-def-456",
  "transfer_url": "https://...",
  "vobiz_response": {...}
}
```

**Response (Error):**
```json
{
  "detail": "Missing 'call_uuid' in request body"
}
```

### POST /transfer-to-human
Called by Vobiz - returns XML for transfer destination

**Returns:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Please hold while I transfer you to a human agent.
    </Speak>
    <Dial>+919148227303</Dial>
</Response>
```

### GET /active-calls
List all currently active calls

**Response:**
```json
{
  "active_calls": ["uuid1", "uuid2"],
  "count": 2,
  "calls": {
    "uuid1": {...},
    "uuid2": {...}
  }
}
```

---

## Advanced Use Cases

### 1. Transfer Based on User Input

Detect when user says "human" or "agent" and trigger transfer automatically.

**Modify bot.py:**
```python
# Add logic to detect transfer keywords
if "human" in user_text.lower() or "agent" in user_text.lower():
    # Call /initiate-transfer API
    await trigger_transfer(call_uuid)
```

### 2. Transfer to Different Departments

Modify `/transfer-to-human` to accept department parameter:

```xml
<Response>
    <Speak>Transferring you to {department}.</Speak>
    <Dial>{department_number}</Dial>
</Response>
```

### 3. Play Hold Music Before Transfer

```xml
<Response>
    <Speak>Please hold.</Speak>
    <Play>https://your-server.com/hold-music.mp3</Play>
    <Dial>+919148227303</Dial>
</Response>
```

### 4. Voicemail if Agent Unavailable

```xml
<Response>
    <Speak>All agents are busy. Please leave a message.</Speak>
    <Record
        action="https://your-server.com/voicemail-saved"
        maxLength="120"
    />
</Response>
```

---

## Troubleshooting

### Transfer Doesn't Work

**Check:**
1. Is call still active? (use `/active-calls`)
2. Is `call_uuid` correct?
3. Is `PUBLIC_URL` set in `.env`?
4. Check server logs for errors

**Test transfer endpoint manually:**
```bash
curl https://your-ngrok-url.ngrok-free.app/transfer-to-human
```
Should return XML.

### Bot Continues Talking After Transfer

- Vobiz might be returning an error
- Check server logs for Vobiz API response
- Verify `call_uuid` is valid

### Transfer to Wrong Number

- Check `TRANSFER_AGENT_NUMBER` in `.env`
- Default is `+919148227303`

---

## Complete Example Session

```bash
# Terminal 1: Start server
python server.py

# Terminal 2: Start ngrok
ngrok http 7860

# Update .env with ngrok URL, restart server

# Terminal 3: Make call
curl -X POST https://api.vobiz.ai/.../Call/ \
  -H "X-Auth-ID: MA_SYQRLN1K" \
  -H "X-Auth-Token: TOKEN" \
  -d '{
    "from": "+918071387428",
    "to": "+919148227303",
    "answer_url": "https://YOUR_NGROK.ngrok-free.app/answer"
  }'

# Save call_uuid from response

# Wait for call to connect and bot to start talking

# Transfer the call
curl -X POST http://localhost:7860/initiate-transfer \
  -d '{"call_uuid": "YOUR_CALL_UUID"}'

# User hears: "Please hold while I transfer you..."
# Call connects to agent at +919148227303
```

---

## Production Deployment

For production:

1. **Store active calls in Redis** (not in-memory dict)
2. **Add authentication** to `/initiate-transfer` endpoint
3. **Implement transfer queue** for multiple agents
4. **Add transfer analytics** (track transfer reasons, duration, etc.)
5. **Webhook notifications** when transfer completes

---

**Transfer feature ready!** 🎉📞👨‍💼
