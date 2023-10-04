"""
Django rules-based permissions for tagging
"""
from __future__ import annotations

from typing import Callable, Union

import django.contrib.auth.models
# typing support in rules depends on https://github.com/dfunckt/django-rules/pull/177
import rules  # type: ignore[import]
from attrs import define

from .models import Tag, Taxonomy

UserType = Union[
    django.contrib.auth.models.User, django.contrib.auth.models.AnonymousUser
]


# Global staff are taxonomy admins.
# (Superusers can already do anything)
is_taxonomy_admin: Callable[[UserType], bool] = rules.is_staff


@define
class ChangeObjectTagPermissionItem:
    """
    Pair of taxonomy and object_id used for permission checking.
    """

    taxonomy: Taxonomy
    object_id: str


@rules.predicate
def can_view_taxonomy(user: UserType, taxonomy: Taxonomy | None = None) -> bool:
    """
    Anyone can view an enabled taxonomy or list all taxonomies,
    but only taxonomy admins can view a disabled taxonomy.
    """
    return not taxonomy or taxonomy.cast().enabled or is_taxonomy_admin(user)


@rules.predicate
def can_change_taxonomy(user: UserType, taxonomy: Taxonomy | None = None) -> bool:
    """
    Even taxonomy admins cannot change system taxonomies.
    """
    return is_taxonomy_admin(user) and (
        not taxonomy or bool(taxonomy and not taxonomy.cast().system_defined)
    )


@rules.predicate
def can_change_tag(user: UserType, tag: Tag | None = None) -> bool:
    """
    Even taxonomy admins cannot add tags to system taxonomies (their tags are system-defined), or free-text taxonomies
    (these don't have predefined tags).
    """
    taxonomy = tag.taxonomy.cast() if (tag and tag.taxonomy) else None
    return is_taxonomy_admin(user) and (
        not tag
        or not taxonomy
        or (taxonomy and not taxonomy.allow_free_text and not taxonomy.system_defined)
    )


@rules.predicate
def can_change_object_tag_objectid(_user: UserType, _object_id: str) -> bool:
    """
    Nobody can create or modify object tags without checking the permission for the tagged object.

    This rule should be defined in other apps for proper permission checking.
    """
    return False


@rules.predicate
def can_change_object_tag(
    user: UserType, perm_obj: ChangeObjectTagPermissionItem | None = None
) -> bool:
    """
    Checks if the user has permissions to create or modify tags on the given taxonomy and object_id.
    """

    # The following code allows METHOD permission (PUT) in the viewset for everyone
    if perm_obj is None:
        return True

    # Checks the permission for the taxonomy
    taxonomy_perm = user.has_perm(
        "oel_tagging.change_objecttag_taxonomy", perm_obj.taxonomy
    )
    if not taxonomy_perm:
        return False

    # Checks the permission for the object_id
    objectid_perm = user.has_perm(
        "oel_tagging.change_objecttag_objectid",
        # The obj arg expects an object, but we are passing a string
        perm_obj.object_id,  # type: ignore[arg-type]
    )

    return objectid_perm


# Taxonomy
rules.add_perm("oel_tagging.add_taxonomy", can_change_taxonomy)
rules.add_perm("oel_tagging.change_taxonomy", can_change_taxonomy)
rules.add_perm("oel_tagging.delete_taxonomy", can_change_taxonomy)
rules.add_perm("oel_tagging.view_taxonomy", can_view_taxonomy)

# Tag
rules.add_perm("oel_tagging.add_tag", can_change_tag)
rules.add_perm("oel_tagging.change_tag", can_change_tag)
rules.add_perm("oel_tagging.delete_tag", is_taxonomy_admin)
rules.add_perm("oel_tagging.view_tag", rules.always_allow)
rules.add_perm("oel_tagging.list_tag", can_view_taxonomy)

# ObjectTag
rules.add_perm("oel_tagging.add_objecttag", can_change_object_tag)
rules.add_perm("oel_tagging.change_objecttag", can_change_object_tag)
rules.add_perm("oel_tagging.delete_objecttag", can_change_object_tag)
rules.add_perm("oel_tagging.view_objecttag", rules.always_allow)

# Users can tag objects using tags from any taxonomy that they have permission to view
rules.add_perm("oel_tagging.change_objecttag_taxonomy", can_view_taxonomy)
rules.add_perm("oel_tagging.change_objecttag_objectid", can_change_object_tag_objectid)