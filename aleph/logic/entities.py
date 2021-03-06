import logging
from banal import ensure_list
from pprint import pformat  # noqa
from followthemoney import model
from followthemoney.graph import Node
from followthemoney.types import registry

from aleph.core import db, cache
from aleph.model import Entity, Document, Linkage
from aleph.index import entities as index
from aleph.logic.notifications import flush_notifications
from aleph.logic.collections import refresh_collection
from aleph.index import xref as xref_index
from aleph.logic.aggregator import delete_aggregator_entity
from aleph.logic.graph import Graph

log = logging.getLogger(__name__)


def upsert_entity(data, collection, validate=True, sync=False):
    """Create or update an entity in the database. This has a side hustle
    of migrating entities created via the _bulk API or a mapper to a
    database entity in the event that it gets edited by the user.
    """
    entity = None
    entity_id = collection.ns.sign(data.get('id'))
    if entity_id is not None:
        entity = Entity.by_id(entity_id,
                              collection=collection,
                              deleted=True)
    # TODO: migrate softly from index.
    if entity is None:
        entity = Entity.create(data, collection, validate=validate)
    else:
        entity.update(data, collection, validate=validate)
    collection.touch()
    db.session.commit()
    delete_aggregator_entity(collection, entity.id)
    index.index_entity(entity, sync=sync)
    refresh_entity(entity.id, sync=sync)
    refresh_collection(collection.id, sync=sync)
    return entity.id


def refresh_entity(entity_id, sync=False):
    if sync:
        cache.kv.delete(cache.object_key(Entity, entity_id))


def delete_entity(collection, entity, deleted_at=None, sync=False):
    # This is recursive and will also delete any entities which
    # reference the given entity. Usually this is going to be child
    # documents, or directoships referencing a person. It's a pretty
    # dangerous operation, though.
    entity_id = collection.ns.sign(entity.get('id'))
    for adjacent in index.iter_adjacent(entity):
        log.warning("Recursive delete: %r", adjacent)
        delete_entity(collection, adjacent, deleted_at=deleted_at, sync=sync)
    flush_notifications(entity_id, clazz=Entity)
    obj = Entity.by_id(entity_id, collection=collection)
    if obj is not None:
        obj.delete(deleted_at=deleted_at)
    doc = Document.by_id(entity_id, collection=collection)
    if doc is not None:
        doc.delete(deleted_at=deleted_at)
    index.delete_entity(entity_id, sync=sync)
    Linkage.delete_by_entity(entity_id)
    xref_index.delete_xref(collection, entity_id=entity_id, sync=sync)
    delete_aggregator_entity(collection, entity_id)
    refresh_entity(entity_id, sync=sync)
    refresh_collection(collection.id, sync=sync)


def entity_references(entity, authz=None):
    """Given a particular entity, find all the references to it from other
    entities, grouped by the property where they are used."""
    proxy = model.get_proxy(entity)
    node = Node.from_proxy(proxy)
    graph = Graph()
    query = graph.query(authz=authz)
    for prop in proxy.schema.properties.values():
        if not prop.stub:
            continue
        query.edge(node, prop.reverse, count=True)
    for res in query.execute():
        if res.count > 0:
            yield (res.prop, res.count)


def entity_tags(entity, authz=None, edge_types=registry.pivots):
    """Do a search on tags of an entity."""
    proxy = model.get_proxy(entity)
    graph = Graph(edge_types=edge_types)
    query = graph.query(authz=authz)
    for prop, value in proxy.itervalues():
        if prop.type not in graph.edge_types:
            continue
        if prop.specificity(value) < 0.1:
            continue
        query.node(Node(prop.type, value), count=True)
    for res in query.execute():
        field = res.node.type.group
        if res.count > 1:
            yield (field, res.node.value, res.count)


def entity_expand(entity, collection_ids, edge_types, limit,
                  properties=None, authz=None):
    """Expand an entity's graph to find adjacent entities that are connected
    by a common property value(eg: having the same email or phone number), a
    property (eg: Passport entity linked to a Person) or an Entity type edge.
    (eg: Person connected to Company through Directorship)

    collection_ids: list of collection_ids to search
    edge_types: list of FtM Types to expand as edges
    properties: list of FtM Properties to expand as edges.
    limit: max number of entities to return
    """
    proxy = model.get_proxy(entity)
    node = Node.from_proxy(proxy)
    graph = Graph(edge_types=edge_types)
    graph.add(proxy)
    query = graph.query(authz=authz, collection_ids=collection_ids)

    # Get relevant property set
    props = set(proxy.schema.properties.values())
    props = [p for p in props if p.type in graph.edge_types]
    properties = ensure_list(properties)
    if len(properties):
        props = [p for p in props if p.name in properties]

    # Query for reverse properties
    for prop in props:
        if prop.stub:
            query.edge(node, prop.reverse, limit=limit, count=True)
    query.execute()

    # Fill in missing graph entities:
    if limit > 0:
        graph.resolve()

    for prop in props:
        count = len(proxy.get(prop))
        if prop.stub:
            for res in query.patterns:
                if res.prop == prop.reverse:
                    count = res.count
        proxies = set()
        # Too much effort to do this right. This works, too:
        for edge in graph.get_adjacent(node, prop=prop):
            for part in (edge.proxy, edge.source.proxy, edge.target.proxy):
                if part is not None and part != proxy:
                    proxies.add(part)
        if count > 0:
            yield (prop, count, proxies)
