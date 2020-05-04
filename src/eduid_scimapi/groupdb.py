# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Type
from uuid import UUID

from bson import ObjectId

from eduid_groupdb import Group as GraphGroup
from eduid_groupdb import User as GraphUser
from eduid_groupdb import GroupDB
from eduid_scimapi.basedb import ScimApiBaseDB
from eduid_scimapi.group import Group as SCIMGroup

__author__ = 'lundberg'


logger = logging.getLogger(__name__)


@dataclass
class GroupExtensions(object):
    data: Dict[str, Any] = field(default_factory=dict)  # arbitrary third party data

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls: Type[GroupExtensions], data: Mapping) -> GroupExtensions:
        return cls(data=data.get('data', {}),)


@dataclass
class ScimApiGroup(object):
    display_name: str
    group_id: ObjectId = field(default_factory=lambda: ObjectId())
    scim_id: UUID = field(default_factory=lambda: uuid.uuid4())
    version: ObjectId = field(default_factory=lambda: ObjectId())
    created: datetime = field(default_factory=lambda: datetime.utcnow())
    last_modified: datetime = field(default_factory=lambda: datetime.utcnow())
    extensions: GroupExtensions = field(default_factory=lambda: GroupExtensions())
    graph: Optional[GraphGroup] = None

#    @property
#    def etag_remove_this(self):
#        return f'W/"{self.version}"'

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res['scim_id'] = str(res['scim_id'])
        res['_id'] = res.pop('group_id')
        del res['graph']
        return res

    @classmethod
    def from_dict(cls: Type[ScimApiGroup], data: Mapping[str, Any]) -> ScimApiGroup:
        this = dict(data)
        this['scim_id'] = uuid.UUID(this['scim_id'])
        this['group_id'] = this.pop('_id')
        this['extensions'] = GroupExtensions.from_mapping(this['extensions'])
        return cls(**this)


class ScimApiGroupDB(ScimApiBaseDB):
    def __init__(
        self,
        db_uri: str,
        scope: str,
        mongo_uri: str,
        mongo_dbname: str,
        mongo_collection: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(mongo_uri, mongo_dbname, collection=mongo_collection)
        self.graphdb = GroupDB(db_uri=db_uri, scope=scope, config=config)
        logger.info(f'{self} initialised')

    def save(self, group: ScimApiGroup) -> bool:
        group_dict = group.to_dict()

        test_doc = {
            '_id': group.group_id,
            'version': group.version,
        }
        # update the version number and last_modified timestamp
        group_dict['version'] = ObjectId()
        group_dict['last_modified'] = datetime.utcnow()
        result = self._coll.replace_one(test_doc, group_dict, upsert=False)
        if result.modified_count == 0:
            db_group = self._coll.find_one({'_id': group.group_id})
            if db_group:
                logger.debug(f'{self} FAILED Updating group {group} in {self._coll_name}')
                raise RuntimeError('User out of sync, please retry')
            self._coll.insert_one(group_dict)
        # put the new version number and last_modified in the group object after a successful update
        group.version = group_dict['version']
        group.last_modified = group_dict['last_modified']
        logger.debug(f'{self} Updated group {group} in {self._coll_name}')
        import pprint

        extra_debug = pprint.pformat(group_dict, width=120)
        logger.debug(f'Extra debug:\n{extra_debug}')

        return result.acknowledged

    def create_group(self, scim_group: SCIMGroup) -> ScimApiGroup:
        group = ScimApiGroup(extensions=GroupExtensions(data=scim_group.nutid_group_v1.data),
                             display_name=scim_group.display_name)
        group.graph = GraphGroup(identifier=str(group.scim_id), display_name=scim_group.display_name)
        self.graphdb.save(group.graph)
        if not self.save(group):
            logger.warning(f'Creating group {group} probably failed')
        return group

    def update_group(self, scim_group: SCIMGroup, db_group: ScimApiGroup) -> ScimApiGroup:
        changed = False
        member_changed = False
        members = []
        logger.info(f'Updating group {str(db_group.scim_id)}')
        for member in scim_group.members:
            user_updated, group_updated, update_member = None, None, None
            if 'Users' in member.ref:
                user_updated = True
                update_member = db_group.graph.get_member_user(identifier=str(member.value))
            elif 'Groups' in member.ref:
                group_updated = True
                update_member = db_group.graph.get_member_group(identifier=str(member.value))

            # Add a new member
            if update_member is None:
                member_changed = True
                if user_updated:
                    update_member = GraphUser(identifier=str(member.value), display_name=member.display)
                elif group_updated:
                    update_member = db_group.graph.get_member_group(identifier=str(member.value))
                logger.debug(f'Added new member: {update_member}')
            # Update member attributes if they changed
            elif update_member.display_name != member.display:
                member_changed = True
                logger.debug(
                    f'Changed display name for existing member: {update_member.display_name} -> {member.display}'
                )
                update_member.display_name = member.display

            members.append(update_member)

        if db_group.graph.display_name != scim_group.display_name:
            changed = True
            logger.debug(f'Changed display name for group: {db_group.graph.display_name} -> {scim_group.display_name}')
            db_group.graph.display_name = scim_group.display_name

        # Check if there where new, changed or removed members
        if member_changed or set(db_group.graph.members) != set(members):
            changed = True
            logger.debug(f'Old members: {db_group.graph.members}')
            logger.debug(f'New members: {members}')
            db_group.graph.members = members

        _sg_ext = GroupExtensions(data=scim_group.nutid_group_v1.data)
        if db_group.extensions != _sg_ext:
            changed = True
            logger.debug(f'Old extensions: {db_group.extensions}')
            logger.debug(f'New extensions: {_sg_ext}')
            db_group.extensions = _sg_ext

        if changed:
            logger.info(f'Group {str(db_group.scim_id)} changed. Saving.')
            if self.save(db_group):
                db_group.graph = self.graphdb.save(db_group.graph)
            else:
                logger.warning(f'Update of group {db_group} probably failed')

        return db_group

    def get_groups(self) -> List[ScimApiGroup]:
        docs = self._get_documents_by_filter({}, raise_on_missing=False)
        res = []
        for doc in docs:
            group = ScimApiGroup.from_dict(doc)
            group.graph = self.graphdb.get_group(str(group.scim_id))
            logger.info(f'TEST Loaded group {group}')
            assert group.graph
            res += [group]
        return res


    def get_group_by_scim_id(self, scim_id: str) -> Optional[ScimApiGroup]:
        doc = self._get_document_by_attr('scim_id', scim_id, raise_on_missing=False)
        if doc:
            group = ScimApiGroup.from_dict(doc)
            group.graph = self.graphdb.get_group(scim_id)
            return group
        return None

    def get_groups_by_property(self, key: str, value: str, skip=0, limit=100) -> List[ScimApiGroup]:
        docs = self._get_documents_by_filter({key: value}, skip=skip, limit=limit, raise_on_missing=False)
        if not docs:
            return []
        res = []
        for this in docs:
            group = ScimApiGroup.from_dict(this)
            group.graph = self.graphdb.get_group(str(group.scim_id))
            res += [group]
        return res

    def get_groups_for_user(self, user: GraphUser) -> List[ScimApiGroup]:
        user_groups = self.graphdb.get_groups_for_user(user=user)
        res = []
        for graph in user_groups:
            group = self.get_group_by_scim_id(graph.identifier)
            group.graph = graph
            res += [group]
        return res
