

"""server.py

Webhook server to handle outbound call requests, initiate calls via Vobiz API,
and handle subsequent WebSocket connections for Media Streams.
"""

import base64
import json
import os
import urllib.parse
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv(override=True)


# ----------------- HELPERS ----------------- #


async def make_vobiz_call(
    session: aiohttp.ClientSession, to_number: str, from_number: str, answer_url: str
):
    """Make an outbound call using Vobiz's REST API."""
    print("\n[DEBUG] ========== VOBIZ API CALL START ==========")

    auth_id = os.getenv("VOBIZ_AUTH_ID")
    auth_token = os.getenv("VOBIZ_AUTH_TOKEN")

    if not auth_id:
        raise ValueError("Missing Vobiz Auth ID (VOBIZ_AUTH_ID)")

    if not auth_token:
        raise ValueError("Missing Vobiz Auth Token (VOBIZ_AUTH_TOKEN)")

    print(f"[DEBUG] Auth ID: {auth_id}")
    print(f"[DEBUG] Auth Token: {auth_token[:10]}...{auth_token[-10:]}")  # Partial token for security

    headers = {
        "Content-Type": "application/json",
        "X-Auth-ID": auth_id,
        "X-Auth-Token": auth_token,
    }

    data = {
        "to": to_number,
        "from": from_number,
        "answer_url": answer_url,
        "answer_method": "POST",
    }

    url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/"

    print(f"[DEBUG] API URL: {url}")
    print(f"[DEBUG] Request Headers: {headers}")
    print(f"[DEBUG] Request Body: {json.dumps(data, indent=2)}")
    print(f"[DEBUG] Answer URL being sent: {answer_url}")

    try:
        async with session.post(url, headers=headers, json=data) as response:
            response_text = await response.text()
            print(f"[DEBUG] Response Status: {response.status}")
            print(f"[DEBUG] Response Body: {response_text}")

            if response.status != 201:
                print(f"[ERROR] Vobiz API call failed!")
                print(f"[ERROR] Status: {response.status}")
                print(f"[ERROR] Response: {response_text}")
                raise Exception(f"Vobiz API error ({response.status}): {response_text}")

            result = json.loads(response_text)
            print(f"[SUCCESS] Vobiz API call successful!")
            print(f"[SUCCESS] Call UUID: {result.get('call_uuid', 'N/A')}")
            print("[DEBUG] ========== VOBIZ API CALL END ==========\n")
            return result

    except Exception as e:
        print(f"[ERROR] Exception during Vobiz API call: {e}")
        print(f"[ERROR] Exception type: {type(e).__name__}")
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        print("[DEBUG] ========== VOBIZ API CALL END (WITH ERROR) ==========\n")
        raise


def get_host_and_protocol(request: Request = None):
    """Get host and protocol, prioritizing PUBLIC_URL environment variable.

    Returns:
        tuple: (host, protocol)
    """
    public_url = os.getenv("PUBLIC_URL")

    if public_url:
        # Use configured public URL
        print(f"[INFO] Using PUBLIC_URL from environment: {public_url}")
        # Extract host and protocol from PUBLIC_URL
        if public_url.startswith("https://"):
            protocol = "https"
            host = public_url.replace("https://", "").rstrip("/")
        elif public_url.startswith("http://"):
            protocol = "http"
            host = public_url.replace("http://", "").rstrip("/")
        else:
            # No protocol specified, assume https
            protocol = "https"
            host = public_url.rstrip("/")
        print(f"[INFO] Extracted - Host: {host}, Protocol: {protocol}")
        return host, protocol
    else:
        # Fall back to request headers
        if request is None:
            raise ValueError("Request object required when PUBLIC_URL is not set")

        host = request.headers.get("host")
        if not host:
            raise ValueError("Cannot determine server host from request headers")

        print(f"[DEBUG] Host from request headers: {host}")

        # Detect protocol
        # Check X-Forwarded-Proto header (set by ngrok/proxies) or scheme
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            protocol = forwarded_proto
        else:
            # Fall back to checking if host looks like localhost
            protocol = (
                "http"
                if host.startswith("localhost") or host.startswith("127.0.0.1")
                else "https"
            )

        # Warn if using localhost without PUBLIC_URL set
        if host.startswith("localhost") or host.startswith("127.0.0.1"):
            print("[WARNING] ⚠️  Using localhost for URL!")
            print("[WARNING] ⚠️  Vobiz will NOT be able to reach this URL!")
            print("[WARNING] ⚠️  Solution: Set PUBLIC_URL in .env")

        print(f"[DEBUG] Detected protocol: {protocol}")
        return host, protocol


def get_websocket_url(host: str):
    """Construct WebSocket URL for Vobiz Stream XML.

    """
    env = os.getenv("ENV", "local").lower()

    if env == "production":
        # For production, use Pipecat Cloud WebSocket URL (Plivo endpoint works for Vobiz)
        return "wss://api.pipecat.daily.co/ws/plivo"
    else:
        # Return WebSocket URL for local/ngrok deployment
        return f"wss://{host}/ws"


# ----------------- API ----------------- #


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create aiohttp session for Vobiz API calls
    app.state.session = aiohttp.ClientSession()
    yield
    # Close session when shutting down
    await app.state.session.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/start")
async def initiate_outbound_call(request: Request) -> JSONResponse:
    """Handle outbound call request and initiate call via Vobiz."""
    print("Received outbound call request")

    try:
        data = await request.json()

        # Validate request data
        if not data.get("phone_number"):
            raise HTTPException(
                status_code=400, detail="Missing 'phone_number' in the request body"
            )

        # Extract the phone number to dial
        phone_number = str(data["phone_number"])

        # Extract body data if provided
        body_data = data.get("body", {})
        print(f"\n[INFO] Processing outbound call to {phone_number}")
        print(f"[DEBUG] Body data: {body_data}")

        # Get server URL for answer URL using helper function
        host, protocol = get_host_and_protocol(request)

        # Add body data as query parameters to answer URL
        answer_url = f"{protocol}://{host}/answer"
        if body_data:
            body_json = json.dumps(body_data)
            body_encoded = urllib.parse.quote(body_json)
            answer_url = f"{answer_url}?body_data={body_encoded}"

        print(f"[INFO] Answer URL that will be sent to Vobiz: {answer_url}")

        # Get the from number (optional - can be provided in request body)
        from_number = data.get("from_number") or os.getenv("VOBIZ_PHONE_NUMBER")
        print(f"[DEBUG] From number: {from_number}")

        if not from_number:
            print("[ERROR] VOBIZ_PHONE_NUMBER not set in environment and 'from_number' not provided in request")
            raise HTTPException(
                status_code=400,
                detail="Either set VOBIZ_PHONE_NUMBER in .env or provide 'from_number' in request body"
            )

        # Initiate outbound call via Vobiz
        try:
            print(f"[INFO] Initiating Vobiz API call...")
            call_result = await make_vobiz_call(
                session=request.app.state.session,
                to_number=phone_number,
                from_number=from_number,
                answer_url=answer_url,
            )

            # Extract call UUID from Vobiz response
            call_uuid = call_result.get("request_uuid") or call_result.get("call_uuid") or "unknown"
            print(f"[SUCCESS] Call initiated successfully! Call UUID: {call_uuid}")

        except Exception as e:
            print(f"[ERROR] Failed to initiate Vobiz call: {e}")
            import traceback
            print(f"[ERROR] Full traceback:\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to initiate call: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    return JSONResponse(
        {
            "call_uuid": call_uuid,
            "status": "call_initiated",
            "phone_number": phone_number,
        }
    )


@app.api_route("/answer", methods=["GET", "POST"])
async def get_answer_xml(
    request: Request,
    CallUUID: str = Query(None, description="Vobiz call UUID"),
    body_data: str = Query(None, description="JSON encoded body data"),
) -> HTMLResponse:
    """Return XML instructions for connecting call to WebSocket."""
    print("Serving answer XML for outbound call")

    # Parse body data from query parameter
    parsed_body_data = {}
    if body_data:
        try:
            parsed_body_data = json.loads(body_data)
        except json.JSONDecodeError:
            print(f"Failed to parse body data: {body_data}")

    # Log call details
    if CallUUID:
        print(f"Vobiz outbound call UUID: {CallUUID}")
        if parsed_body_data:
            print(f"Body data: {parsed_body_data}")

    try:
        # Get the server host and protocol using helper function
        # This ensures we use PUBLIC_URL if configured
        host, protocol = get_host_and_protocol(request)

        # Get base WebSocket URL (Vobiz uses wss:// protocol)
        base_ws_url = get_websocket_url(host)

        # Add query parameters to WebSocket URL
        query_params = []

        # Add serviceHost for production
        env = os.getenv("ENV", "local").lower()
        if env == "production":
            agent_name = os.getenv("AGENT_NAME")
            org_name = os.getenv("ORGANIZATION_NAME")
            service_host = f"{agent_name}.{org_name}"
            query_params.append(f"serviceHost={service_host}")

        # Add body data if available
        if parsed_body_data:
            body_json = json.dumps(parsed_body_data)
            body_encoded = base64.b64encode(body_json.encode("utf-8")).decode("utf-8")
            query_params.append(f"body={body_encoded}")

        # Construct final WebSocket URL with query parameters
        if query_params:
            ws_url = f"{base_ws_url}?{'&amp;'.join(query_params)}"
        else:
            ws_url = base_ws_url

        # Log the WebSocket URL for debugging
        print(f"[INFO] WebSocket URL being sent to Vobiz: {ws_url}")
        print(f"[INFO] Host: {host}, Environment: {env}")

        # Generate XML response for Vobiz
        
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    
    <Speak>Hello you are talking to Pipecat agent with VoBiz Telephony. Thank you for trusting us.</Speak>
    
    <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">
        {ws_url}
    </Stream>
</Response>"""

        print(f"[DEBUG] XML Response:\n{xml_content}")

        return HTMLResponse(content=xml_content, media_type="application/xml")

    except Exception as e:
        print(f"Error generating answer XML: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate XML: {str(e)}")


@app.api_route("/recording-finished", methods=["GET", "POST"])
async def recording_finished(request: Request) -> HTMLResponse:
    """Called by Vobiz when recording stops"""
    print("\n[RECORDING] ========== RECORDING FINISHED ==========")

    # Vobiz sends form data, not JSON
    data = await request.form()

    recording_url = data.get("RecordUrl")
    duration = data.get("RecordingDuration")
    duration_ms = data.get("RecordingDurationMs")
    recording_id = data.get("RecordingID")
    call_uuid = data.get("CallUUID")
    recording_start_ms = data.get("RecordingStartMs")
    recording_end_ms = data.get("RecordingEndMs")
    recording_end_reason = data.get("RecordingEndReason")

    print(f"[RECORDING] Recording URL: {recording_url}")
    print(f"[RECORDING] Duration: {duration} seconds ({duration_ms} ms)")
    print(f"[RECORDING] Recording ID: {recording_id}")
    print(f"[RECORDING] Call UUID: {call_uuid}")
    print(f"[RECORDING] End Reason: {recording_end_reason}")
    print(f"[RECORDING] Start Time: {recording_start_ms}")
    print(f"[RECORDING] End Time: {recording_end_ms}")

    # Optional: Download the recording
    # if recording_url:
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(recording_url) as resp:
    #             audio_data = await resp.read()
    #             with open(f"recordings/{recording_id}.mp3", "wb") as f:
    #                 f.write(audio_data)
    #     print(f"[RECORDING] Downloaded to recordings/{recording_id}.mp3")

    print("[RECORDING] ========== RECORDING FINISHED END ==========\n")

    # Return empty XML response
    return HTMLResponse(content="<Response></Response>", media_type="application/xml")


@app.api_route("/recording-ready", methods=["GET", "POST"])
async def recording_ready(request: Request) -> HTMLResponse:
    """Called by Vobiz when recording file is ready to download (via callbackUrl)"""
    print("\n[RECORDING CALLBACK] ========== RECORDING FILE READY ==========")

    # Vobiz sends form data
    data = await request.form()

    recording_url = data.get("RecordUrl")
    recording_id = data.get("RecordingID")
    call_uuid = data.get("CallUUID")

    print(f"[RECORDING CALLBACK] Recording file is ready for download!")
    print(f"[RECORDING CALLBACK] URL: {recording_url}")
    print(f"[RECORDING CALLBACK] Recording ID: {recording_id}")
    print(f"[RECORDING CALLBACK] Call UUID: {call_uuid}")

    # Auto-download the recording file with authentication
    if recording_url and recording_id:
        try:
            # Create recordings directory if it doesn't exist
            os.makedirs("recordings", exist_ok=True)

            # Get Vobiz credentials for authenticated download
            auth_id = os.getenv("VOBIZ_AUTH_ID")
            auth_token = os.getenv("VOBIZ_AUTH_TOKEN")

            headers = {
                "X-Auth-ID": auth_id,
                "X-Auth-Token": auth_token,
            }

            print(f"[RECORDING CALLBACK] Downloading recording...")

            async with aiohttp.ClientSession() as session:
                async with session.get(recording_url, headers=headers) as resp:
                    if resp.status == 200:
                        audio_data = await resp.read()
                        filename = f"recordings/{recording_id}.mp3"
                        with open(filename, "wb") as f:
                            f.write(audio_data)
                        print(f"[RECORDING CALLBACK] ✅ Downloaded to {filename}")
                        print(f"[RECORDING CALLBACK] File size: {len(audio_data)} bytes")
                    else:
                        print(f"[RECORDING CALLBACK] ❌ Download failed: HTTP {resp.status}")
                        error_text = await resp.text()
                        print(f"[RECORDING CALLBACK] Error: {error_text}")
        except Exception as e:
            print(f"[RECORDING CALLBACK] ❌ Error downloading recording: {e}")
            import traceback
            print(f"[RECORDING CALLBACK] Traceback:\n{traceback.format_exc()}")

    print("[RECORDING CALLBACK] ========== RECORDING FILE READY END ==========\n")

    # Return empty XML response
    return HTMLResponse(content="<Response></Response>", media_type="application/xml")


async def handle_vobiz_websocket(
    websocket: WebSocket,
    path: str,
    body: str = None,
    serviceHost: str = None,
):
    """Common handler for Vobiz WebSocket connections on any path."""
    print("[DEBUG] ========================================")
    print(f"[DEBUG] WebSocket connection attempt on path: {path}")
    print(f"[DEBUG] Client: {websocket.client}")
    print(f"[DEBUG] Headers: {dict(websocket.headers)}")
    print(f"[DEBUG] Query params - body: {body}, serviceHost: {serviceHost}")
    print("[DEBUG] ========================================")

    try:
        await websocket.accept()
        print("[SUCCESS] WebSocket connection accepted for outbound call")
    except Exception as e:
        print(f"[ERROR] Failed to accept WebSocket connection: {e}")
        raise

    # Decode body parameter if provided
    body_data = {}
    if body:
        try:
            # Base64 decode the JSON (it was base64-encoded in the answer endpoint)
            decoded_json = base64.b64decode(body).decode("utf-8")
            body_data = json.loads(decoded_json)
            print(f"Decoded body data: {body_data}")
        except Exception as e:
            print(f"Error decoding body parameter: {e}")
    else:
        print("No body parameter received")

    try:
        # Import the bot function from the bot module
        from bot import bot
        from pipecat.runner.types import WebSocketRunnerArguments

        print("[DEBUG] Starting bot initialization...")

        # Create runner arguments and run the bot
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        runner_args.handle_sigint = False

        print("[DEBUG] Calling bot function...")
        await bot(runner_args)

        print("[DEBUG] Bot function completed")

    except Exception as e:
        print(f"[ERROR] Error in WebSocket endpoint: {e}")
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
        try:
            await websocket.close()
        except:
            pass


# Register WebSocket endpoints for common paths Vobiz might use
@app.websocket("/ws")
async def websocket_ws(
    websocket: WebSocket,
    body: str = Query(None),
    serviceHost: str = Query(None),
):
    """Handle WebSocket connection at /ws path."""
    await handle_vobiz_websocket(websocket, "/ws", body, serviceHost)


@app.websocket("/")
async def websocket_root(
    websocket: WebSocket,
    body: str = Query(None),
    serviceHost: str = Query(None),
):
    """Handle WebSocket connection at root path."""
    await handle_vobiz_websocket(websocket, "/", body, serviceHost)


@app.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    body: str = Query(None),
    serviceHost: str = Query(None),
):
    """Handle WebSocket connection at /stream path."""
    await handle_vobiz_websocket(websocket, "/stream", body, serviceHost)


# ----------------- Main ----------------- #


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
