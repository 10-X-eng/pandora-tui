from textual.widgets import DataTable, TabbedContent
from pandora_tui.ui import PandoraApp, LoginScreen


class Client:
    def __init__(self): self.commands=[]
    async def ensure_service(self): pass
    async def request(self, command, **args):
        self.commands.append((command,args))
        if command=='status': return {'authenticated':True,'busy':False,'status':'Playing', 'track':{'source_id':'PL:1','title':'Song'}}
        if command=='library': return [{'id':'ST:0:1','kind':'station','name':'Station','count':0},
                                       {'id':'PL:1','kind':'playlist','name':'Playlist','count':1}]
        if command=='tracks': return {'tracks':[{'index':0,'title':'Song','artist':'Artist','duration':60}],'total':1}


async def test_browse_active_tab_and_close_detaches():
    client=Client(); app=PandoraApp(client=client, visualizer=False)
    async with app.run_test(size=(140,42)) as pilot:
        await pilot.pause()
        await pilot.press('2'); await pilot.pause()
        assert app.active_source()=='PL:1'
        await pilot.press('b'); await pilot.pause()
        assert app.query_one('#tracks',DataTable).row_count==1
        await pilot.press('q')
    assert not any(c=='quit' for c,a in client.commands)


async def test_login_overlay_during_poll():
    app=PandoraApp(client=Client(), visualizer=False)
    async with app.run_test(size=(120,38)) as pilot:
        await pilot.pause()
        app.push_screen(LoginScreen()); await pilot.pause()
        await app.poll()
        await pilot.press('a','enter'); await pilot.pause()
        assert app.screen.focused.id=='password'


async def test_small_layout_keeps_browser_visible():
    app=PandoraApp(client=Client(), visualizer=False)
    async with app.run_test(size=(60,28)) as pilot:
        await pilot.pause()
        await pilot.press('2','b'); await pilot.pause()
        assert app.query_one('#spectrum').size.height==2
        assert app.query_one('#tracks').size.height>=4
        assert app.query_one('#louder').region.right<=60
        await pilot.resize_terminal(100,42);await pilot.pause()
        assert app.query_one('#spectrum').size.height==5
        await pilot.press('v');await pilot.pause()
        assert not app.query_one('#spectrum').display


async def test_playing_playlist_loads_tracks_on_reconnect_without_browse_key():
    class PlayingClient(Client):
        async def request(self, command, **args):
            if command=='status':
                return {'authenticated':True,'busy':False,'status':'Playing',
                        'track':{'source_id':'PL:1','title':'Song'}}
            return await super().request(command, **args)
    client=PlayingClient();app=PandoraApp(client=client,visualizer=False)
    async with app.run_test(size=(80,40)) as pilot:
        await pilot.pause()
        assert app.query_one('#library-tabs',TabbedContent).active=='stations-tab'
        await pilot.press('3');await pilot.pause()
        assert app.query_one('#tracks',DataTable).row_count==1
        assert app.browse_source=='PL:1'
        calls=sum(c=='tracks' for c,a in client.commands)
        await app.poll();await pilot.pause()
        assert sum(c=='tracks' for c,a in client.commands)==calls


async def test_tracks_follow_station_after_playlist():
    class SwitchingClient(Client):
        radio=False
        async def request(self,command,**args):
            if command=='status' and self.radio:
                return {'authenticated':True,'busy':False,'status':'Playing','source_name':'Station',
                        'track':{'source_id':'ST:0:1','id':'TR:2','title':'Radio song','artist':'Artist'}}
            return await super().request(command,**args)
    client=SwitchingClient();app=PandoraApp(client=client,visualizer=False)
    async with app.run_test(size=(80,40)) as pilot:
        await pilot.pause();await pilot.press('3');await pilot.pause()
        client.radio=True;await app.poll();await pilot.pause()
        assert app.browse_source=='ST:0:1'
        assert 'Radio song' in str(app.query_one('#tracks',DataTable).get_row('current'))
        assert not app.query_one('#more').display
