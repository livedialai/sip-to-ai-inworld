
import asyncio, os, sys, time
sys.path.insert(0, "/root/s2s-inworld-adapter")
from app.ai.inworld_realtime import InworldRealtimeClient

async def main():
    key=os.environ["INWORLD_KEY"]; voice=os.environ["INWORLD_VOICE"]
    prompt=open("/tmp/prompt.txt").read() if os.path.exists("/tmp/prompt.txt") else "Du bist Nadine vom Edeka Markt Bremerhaven. Antworte kurz und freundlich."
    c=InworldRealtimeClient(api_key=key, voice=voice, instructions=prompt,
                            greeting="Guten Tag! Hier ist Nadine vom Edeka Markt Bremerhaven. Was darf ich für Sie tun?")
    t0=time.time()
    await c.connect(); print(f"CONNECTED in {time.time()-t0:.2f}s", flush=True)

    async def collect():
        out=bytearray()
        async for chunk in c.receive_chunks():
            out.extend(chunk)
        return out
    task=asyncio.create_task(collect())

    # Begruessung abwarten
    await asyncio.sleep(2.5)
    pcm=open("/tmp/t_in.pcm","rb").read()
    frames=[pcm[i:i+320] for i in range(0,len(pcm),320)]
    t1=time.time()
    for f in frames:
        if len(f)<320: f=f+b"\x00"*(320-len(f))
        await c.send_pcm16_8k(f); await asyncio.sleep(0.02)
    print(f"SENT {len(frames)} frames ({len(pcm)/16000:.1f}s audio)", flush=True)
    await asyncio.sleep(6)
    audio=task.result() if task.done() else b""
    if not task.done():
        await c.close(); audio=await task
    print("RECEIVED bytes:", len(audio), f"= {len(audio)/16000:.1f}s", flush=True)
    open("/tmp/out.pcm","wb").write(audio)
    await c.close()

asyncio.run(main())
