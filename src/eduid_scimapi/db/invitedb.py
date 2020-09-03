from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple, Type
from uuid import UUID

from bson import ObjectId

from eduid_scimapi.db.basedb import ScimApiBaseDB
from eduid_scimapi.db.common import ScimApiEmail, ScimApiName, ScimApiPhoneNumber, ScimApiProfile

__author__ = 'lundberg'


logger = logging.getLogger(__name__)


@dataclass
class ScimApiInvite:
    invite_id: ObjectId = field(default_factory=lambda: ObjectId())
    scim_id: UUID = field(default_factory=lambda: uuid.uuid4())
    external_id: Optional[str] = None
    name: ScimApiName = field(default_factory=lambda: ScimApiName())
    emails: List[ScimApiEmail] = field(default_factory=list)
    phone_numbers: List[ScimApiPhoneNumber] = field(default_factory=list)
    nin: Optional[str] = field(default=None)
    preferred_language: Optional[str] = field(default=None)
    completed: Optional[datetime] = field(default=None)
    profiles: Dict[str, ScimApiProfile] = field(default_factory=lambda: {})
    version: ObjectId = field(default_factory=lambda: ObjectId())
    created: datetime = field(default_factory=lambda: datetime.utcnow())
    last_modified: datetime = field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict[str, Any]:
        emails = []
        for email in self.emails:
            emails.append(email.to_dict())
        phone_numbers = []
        for phone_number in self.phone_numbers:
            phone_numbers.append(phone_number.to_dict())
        res = asdict(self)
        res['scim_id'] = str(res['scim_id'])
        res['_id'] = res.pop('invite_id')
        res['emails'] = emails
        res['phone_numbers'] = phone_numbers
        return res

    @classmethod
    def from_dict(cls: Type[ScimApiInvite], data: Mapping[str, Any]) -> ScimApiInvite:
        this = dict(copy.copy(data))  # to not modify callers data
        this['scim_id'] = uuid.UUID(this['scim_id'])
        this['invite_id'] = this.pop('_id')
        # Name
        if this.get('name') is not None:
            this['name'] = ScimApiName.from_dict(this['name'])
        # Emails
        emails = []
        for email in data.get('emails', []):
            emails.append(ScimApiEmail.from_dict(email))
        this['emails'] = emails
        # Phone numbers
        phone_numbers = []
        for number in data.get('phone_numbers', []):
            phone_numbers.append(ScimApiPhoneNumber.from_dict(number))
        this['phone_numbers'] = phone_numbers
        # Profiles
        parsed_profiles = {}
        for k, v in data['profiles'].items():
            parsed_profiles[k] = ScimApiProfile.from_dict(v)
        this['profiles'] = parsed_profiles
        return cls(**this)


class ScimApiInviteDB(ScimApiBaseDB):
    def __init__(self, db_uri: str, collection: str, db_name='eduid_scimapi'):
        super().__init__(db_uri, db_name, collection=collection)
        # Create an index so that scim_id is unique per data owner
        indexes = {
            'unique-scimid': {'key': [('scim_id', 1)], 'unique': True},
            'unique-external-id': {'key': [('external_id', 1)], 'unique': True, 'sparse': True},
        }
        self.setup_indexes(indexes)

    def save(self, invite: ScimApiInvite) -> bool:
        invite_dict = invite.to_dict()

        test_doc = {
            '_id': invite.invite_id,
            'version': invite.version,
        }
        # update the version number and last_modified timestamp
        invite_dict['version'] = ObjectId()
        invite_dict['last_modified'] = datetime.utcnow()
        result = self._coll.replace_one(test_doc, invite_dict, upsert=False)
        if result.modified_count == 0:
            db_invite = self._coll.find_one({'_id': invite.invite_id})
            if db_invite:
                logger.debug(f'{self} FAILED Updating invite {invite} in {self._coll_name}')
                raise RuntimeError('Invite out of sync, please retry')
            self._coll.insert_one(invite_dict)
        # put the new version number and last_modified in the invite object after a successful update
        invite.version = invite_dict['version']
        invite.last_modified = invite_dict['last_modified']
        logger.debug(f'{self} Updated invite {invite} in {self._coll_name}')
        import pprint

        extra_debug = pprint.pformat(invite_dict, width=120)
        logger.debug(f'Extra debug:\n{extra_debug}')

        return result.acknowledged

    def remove(self, invite: ScimApiInvite):
        return self.remove_document(invite.invite_id)

    def get_invite_by_scim_id(self, scim_id: str) -> Optional[ScimApiInvite]:
        docs = self._get_document_by_attr('scim_id', scim_id, raise_on_missing=False)
        if docs:
            return ScimApiInvite.from_dict(docs)
        return None

    def get_invites_by_last_modified(
        self, operator: str, value: datetime, limit: Optional[int] = None, skip: Optional[int] = None
    ) -> Tuple[List[ScimApiInvite], int]:
        # map SCIM filter operators to mongodb filter
        mongo_operator = {'gt': '$gt', 'ge': '$gte'}.get(operator)
        if not mongo_operator:
            raise ValueError('Invalid filter operator')
        spec = {'last_modified': {mongo_operator: value}}
        docs, total_count = self._get_documents_and_count_by_filter(spec=spec, limit=limit, skip=skip)
        invites = [ScimApiInvite.from_dict(x) for x in docs]
        return invites, total_count

    def invite_exists(self, scim_id: str) -> bool:
        return bool(self.db_count(spec={'scim_id': scim_id}, limit=1))
