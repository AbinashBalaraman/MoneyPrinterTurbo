import asyncio
import sys
from agent.services.flow_client import client
import agent.services.flow_batch as fb

async def test_models():
    project_id = "4a9e25d2-f67b-4892-938a-4c281df688e1"
    start_image = "ea580402-941d-41e4-b948-1eaa44d30173"
    models_to_test = [
        "veo_3_1_i2v_lite_low_priority",
        "veo_3_1_i2v_lite",
        "veo_3_1_i2v_s_fast_ultra",
        "veo_3_1_i2v_s_fast",
        "veo_2_0_i2v_fast",
        "veo_3_0_i2v_fast"
    ]
    
    for m in models_to_test:
        print(f"\n--- Testing model: {m} ---")
        try:
            pid = client._batch_project_id(project_id)
            freq = fb.video_request(
                "A stickman jumping", pid, start_image, aspect="VIDEO_ASPECT_RATIO_PORTRAIT",
                model=m,
            )
            payload = await client._batch_payload(
                fb.RPC_GEN_VIDEO, freq, fb.CAPTCHA_VIDEO, timeout=30)
            print(f"Success for {m}! Payload raw preview: {str(payload)[:200]}")
            operation = fb.read_operation(payload)
            print(f"Operation ID: {operation.operation_id}")
            break
        except Exception as e:
            print(f"Failed for {m}: {e}")

if __name__ == "__main__":
    asyncio.run(test_models())
