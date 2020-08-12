# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from bson import ObjectId
from bson.errors import InvalidId
from marshmallow import Schema, ValidationError, fields, missing, post_dump, validate
from marshmallow_dataclass import NewType, class_schema
from marshmallow_enum import EnumField

from eduid_scimapi.utils import make_etag

__author__ = 'lundberg'


class BaseSchema(Schema):
    SKIP_VALUES = [None]

    @post_dump
    def remove_skip_values(self, data, **kwargs):
        return {key: value for key, value in data.items() if value not in self.SKIP_VALUES}


class ObjectIdField(fields.Field):
    def _deserialize(self, value: str, attr, data, **kwargs):
        try:
            return ObjectId(value)
        except InvalidId:
            raise ValidationError(f'invalid ObjectId: {value}')

    def _serialize(self, value: ObjectId, attr, obj, **kwargs):
        if value is None:
            return missing
        return str(value)


class VersionField(ObjectIdField):
    def _deserialize(self, value: str, attr, data, **kwargs):
        try:
            if value.startswith('W/"'):
                value = value.lstrip('W/"').rstrip('"')
            return ObjectId(value)
        except InvalidId:
            raise ValidationError(f'invalid version: {value}')

    def _serialize(self, value: ObjectId, attr, obj, **kwargs):
        if value is None:
            return missing
        return make_etag(value)


class DateTimeField(fields.Field):
    """
    The attribute value MUST be encoded as a valid xsd:dateTime as specified in Section 3.3.7 of
    XML-Schema (https://www.w3.org/TR/xmlschema11-2/) and MUST include both a date and a time.
    """

    def _deserialize(self, value: str, attr, data, **kwargs):
        try:
            return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S%z')
        except ValueError as e:
            raise ValidationError(f'{e}')

    def _serialize(self, value: datetime, attr, obj, **kwargs):
        if value is None:
            return missing
        return datetime.strftime(value, '%Y-%m-%dT%H:%M:%S%z')


class SCIMSchema(Enum):
    CORE_20_USER = 'urn:ietf:params:scim:schemas:core:2.0:User'
    CORE_20_GROUP = 'urn:ietf:params:scim:schemas:core:2.0:Group'
    API_MESSAGES_20_SEARCH_REQUEST = 'urn:ietf:params:scim:api:messages:2.0:SearchRequest'
    API_MESSAGES_20_LIST_RESPONSE = 'urn:ietf:params:scim:api:messages:2.0:ListResponse'
    ERROR = 'urn:ietf:params:scim:api:messages:2.0:Error'
    NUTID_USER_V1 = 'https://scim.eduid.se/schema/nutid/user/v1'
    NUTID_GROUP_V1 = 'https://scim.eduid.se/schema/nutid/group/v1'
    NUTID_INVITE_V1 = 'https://scim.eduid.se/schema/nutid/invite/v1'
    DEBUG_V1 = 'https://scim.eduid.se/schema/nutid-DEBUG/v1'


SCIMSchemaValue = NewType('SCIMSchemaValue', Enum, field=EnumField, enum=SCIMSchema, by_value=True)


class SCIMResourceType(Enum):
    user = 'User'
    group = 'Group'


class EmailType(Enum):
    home = 'home'
    work = 'work'
    other = 'other'


@dataclass(eq=True, frozen=True)
class SubResource:
    value: UUID = field(metadata={'required': True})
    ref: str = field(metadata={'data_key': '$ref', 'required': True})
    display: str = field(metadata={'required': True})

    @property
    def is_user(self):
        return self.ref and '/Users/' in self.ref

    @property
    def is_group(self):
        return self.ref and '/Groups/' in self.ref

    @classmethod
    def from_mapping(cls, data):
        return cls(value=UUID(data['value']), ref=data['$ref'], display=data['display'])


@dataclass
class Meta:
    location: str = field(metadata={'required': True})
    last_modified: datetime = field(metadata={'data_key': 'lastModified', 'required': True})
    resource_type: SCIMResourceType = field(metadata={'data_key': 'resourceType', 'by_value': True, 'required': True})
    created: datetime = field(metadata={'required': True})
    version: ObjectId = field(metadata={'marshmallow_field': VersionField(), 'required': True})


@dataclass
class Name:
    familyName: Optional[str] = None
    givenName: Optional[str] = None
    formatted: Optional[str] = None
    middleName: Optional[str] = None
    honorificPrefix: Optional[str] = None
    honorificSuffix: Optional[str] = None


@dataclass
class Email:
    value: Optional[str] = field(metadata={'validate': validate.Email()})
    display: Optional[str] = None
    type: Optional[EmailType] = field(metadata={'by_value': True}, default=None)
    primary: Optional[bool] = None


@dataclass
class BaseResponse:
    id: UUID = field(metadata={'required': True})
    meta: Meta = field(metadata={'required': True})
    schemas: List[SCIMSchemaValue] = field(default_factory=list, metadata={'required': True})


@dataclass
class BaseCreateRequest:
    schemas: List[SCIMSchemaValue] = field(default_factory=list, metadata={'required': True})


@dataclass
class BaseUpdateRequest:
    id: UUID = field(metadata={'required': True})
    schemas: List[SCIMSchemaValue] = field(default_factory=list, metadata={'required': True})


@dataclass
class SearchRequest:
    schemas: List[SCIMSchemaValue] = field(
        default_factory=lambda: [SCIMSchema.API_MESSAGES_20_SEARCH_REQUEST], metadata={'required': True}
    )
    filter: str = field(default='', metadata={'required': True})
    start_index: int = field(
        default=1, metadata={'data_key': 'startIndex', 'required': False, 'validate': validate.Range(min=1)}
    )
    count: int = field(default=100, metadata={'required': False, 'validate': validate.Range(min=1)})


@dataclass
class ListResponse:
    schemas: List[SCIMSchemaValue] = field(
        default_factory=lambda: [SCIMSchema.API_MESSAGES_20_LIST_RESPONSE], metadata={'required': True}
    )
    resources: List[Dict[Any, Any]] = field(default_factory=list, metadata={'data_key': 'Resources', 'required': True})
    total_results: int = field(default=0, metadata={'data_key': 'totalResults', 'required': True})


SearchRequestSchema = class_schema(SearchRequest, base_schema=BaseSchema)
ListResponseSchema = class_schema(ListResponse, base_schema=BaseSchema)