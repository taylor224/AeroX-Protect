"""Detector worker pure logic: FakeDetector, zone filter, IoU tracker, down-sampler,
and the node-agent reconcile. Heavy deps (torch/cv2/httpx) are lazy → not needed here."""
from worker.detector.backends.base import Detection
from worker.detector.backends.fake import FakeDetector
from worker.detector.node_agent import NodeAgent
from worker.detector.sampler import TrackSampler
from worker.detector.tracker import SimpleTracker
from worker.detector.zones import ZoneFilter


def _d(x1, y1, x2, y2, label='person', cid=0, conf=0.9):
    return Detection((x1, y1, x2, y2), conf, cid, label)


def test_fake_detector():
    fd = FakeDetector({'frame_wh': (100, 100)})
    dets = fd.infer(object(), conf=0.35)
    assert len(dets) == 1 and dets[0].label == 'person'
    assert fd.infer(object(), conf=0.95) == []      # below conf
    assert fd.infer(None) == []


def test_zone_filter_include_and_ignore():
    left = [[[0, 0], [0.5, 0], [0.5, 1], [0, 1]]]
    inside = _d(10, 10, 30, 40)                      # bottom-center (0.2, 0.4) ∈ left
    outside = _d(60, 10, 80, 40)                     # (0.7, 0.4) ∉ left
    inc = ZoneFilter({'include': left}).filter([inside, outside], 100, 100)
    assert inc == [inside]
    ign = ZoneFilter({'ignore': left}).filter([inside, outside], 100, 100)
    assert ign == [outside]


def test_tracker_stable_keys_and_dwell():
    tr = SimpleTracker('sess', 1)
    t1 = tr.update([_d(10, 10, 50, 50)], 1000)
    assert len(t1) == 1 and t1[0].is_new and t1[0].track_key
    key = t1[0].track_key
    t2 = tr.update([_d(12, 12, 52, 52)], 1500)       # overlapping → same track
    assert len(t2) == 1 and t2[0].track_key == key and not t2[0].is_new and t2[0].dwell_ms == 500


def test_tracker_lost_after_max_age():
    tr = SimpleTracker('s', 1, max_age_ms=1000)
    tr.update([_d(10, 10, 50, 50)], 1000)
    out = tr.update([], 2500)                        # 1500ms idle > max_age → lost
    assert len(out) == 1 and out[0].is_lost


def test_sampler_downsamples():
    class T:
        def __init__(self, tk, new=False, lost=False):
            self.track_key, self.is_new, self.is_lost, self.force = tk, new, lost, False

    sm = TrackSampler(interval_ms=1000)
    assert len(sm.sample([T('a', new=True)], 0)) == 1     # new → report
    assert len(sm.sample([T('a')], 500)) == 0             # within interval → skip
    assert len(sm.sample([T('a')], 1000)) == 1            # interval elapsed → report


def test_node_agent_reconcile():
    specs = [{'camera_id': 1, 'epoch': 3}, {'camera_id': 2, 'epoch': 1}]
    start, stop, update = NodeAgent.reconcile(specs, {1: {'camera_id': 1, 'epoch': 3},
                                                      3: {'camera_id': 3, 'epoch': 1}})
    assert [s['camera_id'] for s in start] == [2]
    assert stop == [3] and update == []
    _, _, up = NodeAgent.reconcile([{'camera_id': 1, 'epoch': 5}], {1: {'camera_id': 1, 'epoch': 3}})
    assert up and up[0]['camera_id'] == 1                 # epoch change → re-spec
    _, _, up = NodeAgent.reconcile([{'camera_id': 1, 'epoch': 3, 'min_confidence': 50}],
                                   {1: {'camera_id': 1, 'epoch': 3, 'min_confidence': 35}})
    assert up and up[0]['camera_id'] == 1                 # settings/zone change → re-spec
