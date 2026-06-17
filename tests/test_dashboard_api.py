from tests.conftest import create_user, login

EMPTY_LAYOUT = {'version': 1, 'grid': {'cols': 12, 'rows': 8}, 'cells': []}


def _create_dashboard(client, headers, name='Wall'):
    return client.post('/api/v1/dashboards', headers=headers,
                       json={'name': name, 'layout': EMPTY_LAYOUT})


def test_dashboard_crud(client):
    h = login(client)
    r = _create_dashboard(client, h)
    assert r.status_code == 200
    uuid = r.json['data']['uuid']

    assert client.get('/api/v1/dashboards', headers=h).json['data']['items']
    assert client.get(f'/api/v1/dashboards/{uuid}', headers=h).status_code == 200

    good = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={
        'layout': {'grid': {'cols': 12, 'rows': 8},
                   'cells': [{'i': 'c1', 'x': 0, 'y': 0, 'w': 6, 'h': 4}]}})
    assert good.status_code == 200

    assert client.delete(f'/api/v1/dashboards/{uuid}', headers=h).status_code == 200
    assert client.get(f'/api/v1/dashboards/{uuid}', headers=h).status_code == 404


def test_layout_validation_rejects_out_of_bounds(client):
    h = login(client)
    uuid = _create_dashboard(client, h).json['data']['uuid']
    bad = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={
        'layout': {'grid': {'cols': 12, 'rows': 8}, 'cells': [{'i': 'c1', 'x': 10, 'y': 0, 'w': 6, 'h': 4}]}})
    assert bad.status_code == 400


def test_layout_validation_rejects_duplicate_cell_ids(client):
    h = login(client)
    uuid = _create_dashboard(client, h).json['data']['uuid']
    bad = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={
        'layout': {'grid': {'cols': 12, 'rows': 8},
                   'cells': [{'i': 'c1', 'x': 0, 'y': 0, 'w': 1, 'h': 1},
                             {'i': 'c1', 'x': 1, 'y': 0, 'w': 1, 'h': 1}]}})
    assert bad.status_code == 400


def test_layout_validation_rejects_unknown_camera(client):
    h = login(client)
    uuid = _create_dashboard(client, h).json['data']['uuid']
    bad = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={
        'layout': {'grid': {'cols': 12, 'rows': 8},
                   'cells': [{'i': 'c1', 'x': 0, 'y': 0, 'w': 1, 'h': 1, 'camera_uuid': 'does-not-exist'}]}})
    assert bad.status_code == 400


def test_dashboard_acl_sharing(client):
    h = login(client)
    viewer = create_user(client, h, 'dview', {'dashboards': ['read']})
    uuid = _create_dashboard(client, h).json['data']['uuid']
    vh = login(client, 'dview', 'viewer1234!')

    # not shared yet -> 403
    assert client.get(f'/api/v1/dashboards/{uuid}', headers=vh).status_code == 403

    # owner grants view
    assert client.post(f'/api/v1/dashboards/{uuid}/acl', headers=h,
                       json={'user_id': viewer['id'], 'access': 'view'}).status_code == 200
    assert client.get(f'/api/v1/dashboards/{uuid}', headers=vh).status_code == 200
    # view access cannot edit
    assert client.post(f'/api/v1/dashboards/{uuid}', headers=vh, json={'name': 'x'}).status_code == 403

    # revoke
    assert client.delete(f"/api/v1/dashboards/{uuid}/acl/{viewer['id']}", headers=h).status_code == 200
    assert client.get(f'/api/v1/dashboards/{uuid}', headers=vh).status_code == 403


def test_dashboard_edit_acl_allows_update(client):
    h = login(client)
    editor = create_user(client, h, 'deditor', {'dashboards': ['read', 'update']})
    uuid = _create_dashboard(client, h).json['data']['uuid']
    client.post(f'/api/v1/dashboards/{uuid}/acl', headers=h, json={'user_id': editor['id'], 'access': 'edit'})
    eh = login(client, 'deditor', 'viewer1234!')
    assert client.post(f'/api/v1/dashboards/{uuid}', headers=eh, json={'name': 'Edited'}).status_code == 200


def test_multipage_layout_accepted(client):
    h = login(client)
    uuid = _create_dashboard(client, h).json['data']['uuid']
    layout = {
        'pages': [
            {'name': 'Front', 'grid': {'cols': 12, 'rows': 8},
             'cells': [{'i': 'a', 'x': 0, 'y': 0, 'w': 6, 'h': 4}]},
            {'name': 'Back', 'grid': {'cols': 12, 'rows': 8},
             'cells': [{'i': 'b', 'x': 0, 'y': 0, 'w': 12, 'h': 8}]},
        ],
        'sequence': {'enabled': True, 'dwell_s': 10},
    }
    r = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={'layout': layout})
    assert r.status_code == 200, r.json
    got = client.get(f'/api/v1/dashboards/{uuid}', headers=h).json['data']['layout']
    assert len(got['pages']) == 2 and got['sequence']['enabled'] is True


def test_multipage_validation_rejects_bad_page_and_dwell(client):
    h = login(client)
    uuid = _create_dashboard(client, h).json['data']['uuid']
    # cell out of bounds inside a page
    bad = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={'layout': {
        'pages': [{'grid': {'cols': 12, 'rows': 8}, 'cells': [{'i': 'x', 'x': 20, 'y': 0, 'w': 4, 'h': 4}]}]}})
    assert bad.status_code == 400
    # dwell too small
    bad2 = client.post(f'/api/v1/dashboards/{uuid}', headers=h, json={'layout': {
        'pages': [{'grid': {'cols': 12, 'rows': 8}, 'cells': []}], 'sequence': {'dwell_s': 1}}})
    assert bad2.status_code == 400
