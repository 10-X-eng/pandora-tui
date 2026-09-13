import asyncio
from unittest.mock import Mock
import pytest
from pandora_tui.api import PandoraAPI
from pandora_tui.engine import Engine
from pandora_tui.errors import AppError
from pandora_tui.models import Track, Source
from pandora_tui.mpris import Player, Playlists


def track(index=0):
    return Track('TR:1', 'PL:1', index, 'Song', 'Artist', 'Album', 100, '',
                 'https://cdn.example/secret', 'secret-token', ['SKIP', 'SEEK'])


class Audio:
    def __init__(self, callback, **kwargs): self.callback=callback; self.paused=True
    async def start(self): pass
    async def volume(self, value): pass
    async def load(self, track): self.paused=False
    async def pause(self, value): self.paused=value
    async def stop(self): self.paused=True
    async def close(self): pass


@pytest.fixture
def engine():
    api=Mock(); api.source.return_value=track(); api.advance.return_value=track(1)
    e=Engine(api, Mock(), player_factory=Audio)
    e.sources=[Source('PL:1','Playlist','playlist')]
    return e


async def test_controls_and_stale_eof(engine):
    await engine.choose('PL:1')
    first=engine.track
    await engine.pause()
    assert engine.status=='Paused' and engine.player.paused
    await engine.play()
    assert engine.status=='Playing' and not engine.player.paused
    await engine.next()
    await engine.next(natural=True, expected=first)
    assert engine.api.advance.call_count==1
    assert engine.track.index==1
    await engine.close()


async def test_skip_failure_keeps_player_paused(engine):
    await engine.choose('PL:1')
    engine.api.advance.side_effect=AppError('No skips remaining')
    with pytest.raises(AppError): await engine.next()
    assert engine.status=='Paused' and engine.player.paused and not engine.busy
    await engine.close()


async def test_forbidden_skip_does_not_call_server(engine):
    await engine.choose('PL:1')
    engine.track.interactions=[]
    with pytest.raises(AppError): await engine.next()
    engine.api.advance.assert_not_called()
    assert engine.status=='Playing'
    await engine.close()


async def test_natural_end_advances_without_skip_permission(engine):
    await engine.choose('PL:1'); engine.track.interactions=[]
    await engine.next(natural=True, expected=engine.track)
    assert engine.api.advance.call_args.args[-1] is True
    await engine.close()


def test_secrets_excluded_from_public_state_and_mpris(engine):
    engine.track=track()
    public=repr(engine.snapshot())+repr(Player(engine).Metadata)+repr(engine.track)
    assert 'secret-token' not in public and 'cdn.example' not in public


def test_audio_urls_upgrade_tls_and_reject_local_files():
    api=PandoraAPI('test')
    assert api._track({'item':{'audioUrl':'http://cdn.example/song'}}).audio_url=='https://cdn.example/song'
    with pytest.raises(AppError): api._track({'item':{'audioUrl':'file:///etc/passwd'}})


def test_library_pagination_and_duplicates():
    api=PandoraAPI('test');api._radio=Mock(return_value={'stations':[{'stationId':'2','stationName':'Station'}]})
    api._web=Mock(side_effect=[{'items':[{'pandoraId':'PL:1','name':'First'}], 'totalCount':3},
        {'items':[{'pandoraId':'PL:1','name':'First'},{'pandoraId':'PL:2','name':'Second'}], 'totalCount':3}])
    sources=api.library()
    assert [s.id for s in sources]==['ST:0:2','PL:1','PL:2']
    assert api._web.call_args.args[1]['request']['offset']==1


def test_track_page_indices():
    api=PandoraAPI('test');api._web=Mock(side_effect=[{'tracks':[{'pandoraId':'TR:1'}],'totalTracks':51},
        {'TR:1':{'name':'Title','artistName':'Artist'}}])
    page=api.tracks('PL:1',50)
    assert page['tracks'][0]['index']==50 and page['tracks'][0]['title']=='Title'


def test_empty_end_ack_fetches_cursor_without_repeating_mutation():
    api=PandoraAPI('test')
    api._web=Mock(side_effect=[{}, {'item':{'audioUrl':'https://cdn.example/song','index':2}}])
    assert api.advance(track(),100,natural=True).index==2
    assert [c.args[0] for c in api._web.call_args_list]==['v1/event/ended','v1/playback/current']


def test_simultaneous_stream_violation_has_actionable_error():
    api=PandoraAPI('test')
    with pytest.raises(AppError,match='another device'):
        api._track({'item':{'type':'SimStreamViolation','audioUrl':'https://cdn.example/notice'}})


def test_station_preview_excludes_stream_and_token():
    api=PandoraAPI('test')
    api._web=Mock(return_value={'item':{'type':'Track','songName':'Next song',
        'audioUrl':'https://cdn.example/private','trackToken':'private-token'}})
    preview=api.up_next('ST:0:1')
    assert preview['title']=='Next song'
    assert 'private' not in repr(preview)
    assert api._web.call_args.args[0]=='v1/playback/peek'
