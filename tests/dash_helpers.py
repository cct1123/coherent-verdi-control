"""Build real Dash callback requests for hardware-free client tests."""


def callback_request(app, output_id, *, trigger="refresh", count=1, state=None):
    key = next(key for key in app.callback_map if output_id in key)
    entry = app.callback_map[key]
    output = entry["output"]

    def describe(item):
        if isinstance(item, list):
            return [describe(child) for child in item]
        return {"id": item.component_id, "property": item.component_property}

    state = {"history-cursor": 0, "connection-generation": 0} | (state or {})
    return {
        "output": key,
        "outputs": describe(output),
        "inputs": [
            {**item, "value": count if item["id"] == trigger else 0} for item in entry["inputs"]
        ],
        "state": [{**item, "value": (state or {}).get(item["id"])} for item in entry["state"]],
        "changedPropIds": [f"{trigger}.{'n_intervals' if trigger == 'refresh' else 'n_clicks'}"],
    }
