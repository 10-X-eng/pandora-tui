"""Opt-in account smoke test. Credentials are prompted interactively, never logged."""
import asyncio
from getpass import getpass
import uuid
from pandora_tui.api import PandoraAPI
from pandora_tui.engine import Engine
from pandora_tui.credentials import CredentialStore
from pandora_tui import ipc
from pandora_tui.errors import AppError

async def main():
    try:
        await ipc.request("status")
    except AppError:
        pass
    else:
        raise SystemExit("Stop the background player before running this standalone test; Pandora permits one session.")
    email = input("Pandora email: ").strip()
    password = getpass("Pandora password: ")
    engine=Engine(PandoraAPI(str(uuid.uuid4())),CredentialStore(),silent=True)
    await engine.start()
    try:
        await engine.login(email,password)
        password = ""
        station=next(s for s in engine.sources if s.kind=='station' and s.name!='QuickMix')
        await engine.choose(station.id); await asyncio.sleep(4)
        assert engine.position>0 and not engine.error and engine.track.item_type=='Track',engine.error
        print('Station audio decoded',flush=True)
        await engine.next(); await asyncio.sleep(4)
        assert engine.position>0 and not engine.error and engine.track.item_type=='Track',engine.error
        print('Station skip decoded',flush=True)
        playlist=next(s for s in engine.sources if s.kind=='playlist' and s.count>1)
        await engine.choose(playlist.id); await asyncio.sleep(3)
        first=engine.track
        assert 'SEEK' in first.interactions
        await engine.player.command('seek',first.duration-2,'absolute')
        for _ in range(25):
            await asyncio.sleep(1)
            if engine.track is not first and engine.position>0: break
        assert engine.track is not first and engine.status=='Playing',engine.error
        print('Natural end advanced',flush=True)
    finally: await engine.close()

if __name__=='__main__':
    asyncio.run(main())
