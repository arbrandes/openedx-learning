"""
Test the tagging APIs
"""
from __future__ import annotations

from typing import Any

import ddt  # type: ignore[import]
import pytest
from django.test import TestCase, override_settings

import openedx_tagging.core.tagging.api as tagging_api
from openedx_tagging.core.tagging.models import ObjectTag, Tag, Taxonomy

from .test_models import TestTagTaxonomyMixin, get_tag

test_languages = [
    ("az", "Azerbaijani"),
    ("en", "English"),
    ("id", "Indonesian"),
    ("ga", "Irish"),
    ("pl", "Polish"),
    ("qu", "Quechua"),
    ("zu", "Zulu"),
]
# Languages that contains 'ish'
filtered_test_languages = [
    ("en", "English"),
    ("ga", "Irish"),
    ("pl", "Polish"),
]


@ddt.ddt
class TestApiTagging(TestTagTaxonomyMixin, TestCase):
    """
    Test the Tagging API methods.
    """

    def test_create_taxonomy(self) -> None:  # Note: we must specify '-> None' to opt in to type checking
        params: dict[str, Any] = {
            "name": "Difficulty",
            "description": "This taxonomy contains tags describing the difficulty of an activity",
            "enabled": False,
            "required": True,
            "allow_multiple": True,
            "allow_free_text": True,
        }
        taxonomy = tagging_api.create_taxonomy(**params)
        for param, value in params.items():
            assert getattr(taxonomy, param) == value
        assert not taxonomy.system_defined
        assert taxonomy.visible_to_authors

    def test_bad_taxonomy_class(self) -> None:
        with self.assertRaises(ValueError) as exc:
            tagging_api.create_taxonomy(
                name="Bad class",
                taxonomy_class=str,  # type: ignore[arg-type]
            )
        assert "<class 'str'> must be a subclass of Taxonomy" in str(exc.exception)

    def test_get_taxonomy(self) -> None:
        tax1 = tagging_api.get_taxonomy(1)
        assert tax1 == self.taxonomy
        no_tax = tagging_api.get_taxonomy(200)
        assert no_tax is None

    def test_get_taxonomies(self) -> None:
        tax1 = tagging_api.create_taxonomy("Enabled")
        tax2 = tagging_api.create_taxonomy("Disabled", enabled=False)
        tax3 = Taxonomy.objects.get(name="Import Taxonomy Test")
        with self.assertNumQueries(1):
            enabled = list(tagging_api.get_taxonomies())
        assert enabled == [
            tax1,
            tax3,
            self.language_taxonomy,
            self.taxonomy,
            self.system_taxonomy,
            self.user_taxonomy,
        ] + self.dummy_taxonomies
        assert str(enabled[0]) == f"<Taxonomy> ({tax1.id}) Enabled"
        assert str(enabled[1]) == "<Taxonomy> (5) Import Taxonomy Test"
        assert str(enabled[2]) == "<LanguageTaxonomy> (-1) Languages"
        assert str(enabled[3]) == "<Taxonomy> (1) Life on Earth"
        assert str(enabled[4]) == "<SystemDefinedTaxonomy> (4) System defined taxonomy"

        with self.assertNumQueries(1):
            disabled = list(tagging_api.get_taxonomies(enabled=False))
        assert disabled == [tax2]
        assert str(disabled[0]) == f"<Taxonomy> ({tax2.id}) Disabled"

        with self.assertNumQueries(1):
            both = list(tagging_api.get_taxonomies(enabled=None))
        assert both == [
            tax2,
            tax1,
            tax3,
            self.language_taxonomy,
            self.taxonomy,
            self.system_taxonomy,
            self.user_taxonomy,
        ] + self.dummy_taxonomies

    @override_settings(LANGUAGES=test_languages)
    def test_get_tags(self) -> None:
        self.setup_tag_depths()
        assert tagging_api.get_tags(self.taxonomy) == [
            *self.domain_tags,
            *self.kingdom_tags,
            *self.phylum_tags,
        ]
        assert tagging_api.get_tags(self.system_taxonomy) == self.system_tags
        tags = tagging_api.get_tags(self.language_taxonomy)
        langs = [tag.external_id for tag in tags]
        expected_langs = [lang[0] for lang in test_languages]
        assert langs == expected_langs

    @override_settings(LANGUAGES=test_languages)
    def test_get_root_tags(self):
        assert tagging_api.get_root_tags(self.taxonomy) == self.domain_tags
        assert tagging_api.get_root_tags(self.system_taxonomy) == self.system_tags
        tags = tagging_api.get_root_tags(self.language_taxonomy)
        langs = [tag.external_id for tag in tags]
        expected_langs = [lang[0] for lang in test_languages]
        assert langs == expected_langs

    @override_settings(LANGUAGES=test_languages)
    def test_search_tags(self):
        assert tagging_api.search_tags(
            self.taxonomy,
            search_term='eU'
        ) == self.filtered_tags

        tags = tagging_api.search_tags(self.language_taxonomy, search_term='IsH')
        langs = [tag.external_id for tag in tags]
        expected_langs = [lang[0] for lang in filtered_test_languages]
        assert langs == expected_langs

    def test_get_children_tags(self):
        assert tagging_api.get_children_tags(
            self.taxonomy,
            self.animalia.id,
        ) == self.phylum_tags
        assert tagging_api.get_children_tags(
                self.taxonomy,
                self.animalia.id,
                search_term='dA',
        ) == self.filtered_phylum_tags
        assert not tagging_api.get_children_tags(
            self.system_taxonomy,
            self.system_taxonomy_tag.id,
        )
        assert not tagging_api.get_children_tags(
            self.language_taxonomy,
            self.english_tag,
        )

    def check_object_tag(
        self,
        object_tag: ObjectTag,
        taxonomy: Taxonomy | None,
        tag: Tag | None,
        name: str,
        value: str,
    ) -> None:
        """
        Verifies that the properties of the given object_tag (once refreshed from the database) match those given.
        """
        object_tag.refresh_from_db()
        assert object_tag.taxonomy == taxonomy
        assert object_tag.tag == tag
        assert object_tag.name == name
        assert object_tag.value == value

    def test_resync_object_tags(self) -> None:
        self.taxonomy.allow_multiple = True
        self.taxonomy.save()
        open_taxonomy = Taxonomy.objects.create(name="Freetext Life", allow_free_text=True, allow_multiple=True)

        object_id = "obj1"
        # Create some tags:
        tagging_api.tag_object(self.taxonomy, [self.archaea.value, self.bacteria.value], object_id)  # Regular tags
        tagging_api.tag_object(open_taxonomy, ["foo", "bar"], object_id)  # Free text tags

        # At first, none of these will be deleted:
        assert [(t.value, t.is_deleted) for t in tagging_api.get_object_tags(object_id)] == [
            (self.archaea.value, False),
            (self.bacteria.value, False),
            ("foo", False),
            ("bar", False),
        ]

        # Delete "bacteria" from the taxonomy:
        self.bacteria.delete()  # TODO: add an API method for this

        assert [(t.value, t.is_deleted) for t in tagging_api.get_object_tags(object_id)] == [
            (self.archaea.value, False),
            (self.bacteria.value, True),  # <--- deleted! But the value is preserved.
            ("foo", False),
            ("bar", False),
        ]

        # Re-syncing the tags at this point does nothing:
        tagging_api.resync_object_tags()

        # Now re-create the tag
        self.bacteria.save()

        # Then re-sync the tags:
        changed = tagging_api.resync_object_tags()
        assert changed == 1

        # Now the tag is not deleted:
        assert [(t.value, t.is_deleted) for t in tagging_api.get_object_tags(object_id)] == [
            (self.archaea.value, False),
            (self.bacteria.value, False),  # <--- not deleted
            ("foo", False),
            ("bar", False),
        ]

        # Re-syncing the tags now does nothing:
        changed = tagging_api.resync_object_tags()
        assert changed == 0

    def test_tag_object(self):
        self.taxonomy.allow_multiple = True

        test_tags = [
            [
                self.archaea,
                self.eubacteria,
                self.chordata,
            ],
            [
                self.chordata,
                self.archaebacteria,
            ],
            [
                self.archaebacteria,
                self.archaea,
            ],
        ]

        # Tag and re-tag the object, checking that the expected tags are returned and deleted
        for tag_list in test_tags:
            tagging_api.tag_object(
                self.taxonomy,
                [t.value for t in tag_list],
                "biology101",
            )
            # Ensure the expected number of tags exist in the database
            object_tags = tagging_api.get_object_tags("biology101", taxonomy_id=self.taxonomy.id)
            # And the expected number of tags were returned
            assert len(object_tags) == len(tag_list)
            for index, object_tag in enumerate(object_tags):
                object_tag.full_clean()  # Should not raise any ValidationErrors
                assert object_tag.tag_id == tag_list[index].id
                assert object_tag._value == tag_list[index].value  # pylint: disable=protected-access
                assert object_tag.taxonomy == self.taxonomy
                assert object_tag.name == self.taxonomy.name
                assert object_tag.object_id == "biology101"

    def test_tag_object_free_text(self):
        self.taxonomy.allow_free_text = True
        tagging_api.tag_object(
            self.taxonomy,
            ["Eukaryota Xenomorph"],
            "biology101",
        )
        object_tags = tagging_api.get_object_tags("biology101")
        assert len(object_tags) == 1
        object_tag = object_tags[0]
        object_tag.full_clean()  # Should not raise any ValidationErrors
        assert object_tag.taxonomy == self.taxonomy
        assert object_tag.name == self.taxonomy.name
        assert object_tag._value == "Eukaryota Xenomorph"  # pylint: disable=protected-access
        assert object_tag.get_lineage() == ["Eukaryota Xenomorph"]
        assert object_tag.object_id == "biology101"

    def test_tag_object_no_multiple(self):
        with pytest.raises(ValueError) as excinfo:
            tagging_api.tag_object(self.taxonomy, ["A", "B"], "biology101")
        assert "only allows one tag per object" in str(excinfo.value)

    def test_tag_object_required(self):
        self.taxonomy.required = True
        with pytest.raises(ValueError) as excinfo:
            tagging_api.tag_object(self.taxonomy, [], "biology101")
        assert "requires at least one tag per object" in str(excinfo.value)

    def test_tag_object_invalid_tag(self):
        with pytest.raises(tagging_api.TagDoesNotExist) as excinfo:
            tagging_api.tag_object(self.taxonomy, ["Eukaryota Xenomorph"], "biology101")
        assert "Tag matching query does not exist." in str(excinfo.value)

    def test_tag_object_string(self) -> None:
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                'string',  # type: ignore[arg-type]
                "biology101",
            )
        assert "Tags must be a list, not str." in str(exc.exception)

    def test_tag_object_integer(self) -> None:
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                1,  # type: ignore[arg-type]
                "biology101",
            )
        assert "Tags must be a list, not int." in str(exc.exception)

    def test_tag_object_same_id(self) -> None:
        # Tag the object with the same tag twice
        tagging_api.tag_object(
            self.taxonomy,
            [self.eubacteria.value],
            "biology101",
        )
        tagging_api.tag_object(
            self.taxonomy,
            [self.eubacteria.value],
            "biology101",
        )
        object_tags = tagging_api.get_object_tags("biology101")
        assert len(object_tags) == 1
        assert str(object_tags[0]) == "<ObjectTag> biology101: Life on Earth=Eubacteria"

    def test_tag_object_same_value(self) -> None:
        # Tag the object with the same value twice
        tagging_api.tag_object(
            self.taxonomy,
            [self.eubacteria.value, self.eubacteria.value],
            "biology101",
        )
        object_tags = tagging_api.get_object_tags("biology101")
        assert len(object_tags) == 1
        assert str(object_tags[0]) == "<ObjectTag> biology101: Life on Earth=Eubacteria"

    def test_tag_object_same_value_multiple_free(self) -> None:
        self.taxonomy.allow_multiple = True
        self.taxonomy.allow_free_text = True
        self.taxonomy.save()
        # Tag the object with the same value twice
        tagging_api.tag_object(
            self.taxonomy,
            ["tag1", "tag1"],
            "biology101",
        )
        object_tags = tagging_api.get_object_tags("biology101")
        assert len(object_tags) == 1

    def test_tag_object_case_id(self) -> None:
        """
        Test that the case of the object_id is preserved.
        """
        tagging_api.tag_object(
            self.taxonomy,
            [self.eubacteria.value],
            "biology101",
        )

        tagging_api.tag_object(
            self.taxonomy,
            [self.archaea.value],
            "BIOLOGY101",
        )

        object_tags_lower = tagging_api.get_object_tags(
            taxonomy_id=self.taxonomy.pk,
            object_id="biology101",
        )

        assert len(object_tags_lower) == 1
        assert object_tags_lower[0].tag_id == self.eubacteria.id

        object_tags_upper = tagging_api.get_object_tags(
            taxonomy_id=self.taxonomy.pk,
            object_id="BIOLOGY101",
        )

        assert len(object_tags_upper) == 1
        assert object_tags_upper[0].tag_id == self.archaea.id

    @override_settings(LANGUAGES=test_languages)
    def test_tag_object_language_taxonomy(self) -> None:
        tags_list = [
            ["Azerbaijani"],
            ["English"],
        ]

        for tags in tags_list:
            tagging_api.tag_object(self.language_taxonomy, tags, "biology101")

            # Ensure the expected number of tags exist in the database
            object_tags = tagging_api.get_object_tags("biology101")
            # And the expected number of tags were returned
            assert len(object_tags) == len(tags)
            for index, object_tag in enumerate(object_tags):
                object_tag.full_clean()  # Check full model validation
                assert object_tag.value == tags[index]
                assert not object_tag.is_deleted
                assert object_tag.taxonomy == self.language_taxonomy
                assert object_tag.name == self.language_taxonomy.name
                assert object_tag.object_id == "biology101"

    @override_settings(LANGUAGES=test_languages)
    def test_tag_object_language_taxonomy_invalid(self) -> None:
        with self.assertRaises(tagging_api.TagDoesNotExist):
            tagging_api.tag_object(
                self.language_taxonomy,
                ["Spanish"],
                "biology101",
            )

    def test_tag_object_model_system_taxonomy(self) -> None:
        users = [
            self.user_1,
            self.user_2,
        ]

        for user in users:
            tags = [user.username]
            tagging_api.tag_object(self.user_taxonomy, tags, "biology101")

            # Ensure the expected number of tags exist in the database
            object_tags = tagging_api.get_object_tags("biology101")
            # And the expected number of tags were returned
            assert len(object_tags) == len(tags)
            for object_tag in object_tags:
                object_tag.full_clean()  # Check full model validation
                assert object_tag.tag
                assert object_tag.tag.external_id == str(user.id)
                assert object_tag.tag.value == user.username
                assert not object_tag.is_deleted
                assert object_tag.taxonomy == self.user_taxonomy
                assert object_tag.name == self.user_taxonomy.name
                assert object_tag.object_id == "biology101"

    def test_tag_object_model_system_taxonomy_invalid(self) -> None:
        tags = ["Invalid id"]
        with self.assertRaises(tagging_api.TagDoesNotExist):
            tagging_api.tag_object(self.user_taxonomy, tags, "biology101")

    def test_tag_object_limit(self) -> None:
        """
        Test that the tagging limit is enforced.
        """
        # The user can add up to 100 tags to a object
        for taxonomy in self.dummy_taxonomies:
            tagging_api.tag_object(
                taxonomy,
                ["Dummy Tag"],
                "object_1",
            )

        # Adding a new tag should fail
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                ["Eubacteria"],
                "object_1",
            )
            assert exc.exception
            assert "Cannot add more than 100 tags to" in str(exc.exception)

        # Updating existing tags should work
        for taxonomy in self.dummy_taxonomies:
            tagging_api.tag_object(
                taxonomy,
                ["New Dummy Tag"],
                "object_1",
            )

        # Updating existing tags adding a new one should fail
        for taxonomy in self.dummy_taxonomies:
            with self.assertRaises(ValueError) as exc:
                tagging_api.tag_object(
                    taxonomy,
                    ["New Dummy Tag 1", "New Dummy Tag 2"],
                    "object_1",
                )
                assert exc.exception
                assert "Cannot add more than 100 tags to" in str(exc.exception)

    def test_get_object_tags(self) -> None:
        # Alpha tag has no taxonomy
        alpha = ObjectTag(object_id="abc")
        alpha.name = self.taxonomy.name
        alpha.value = self.mammalia.value
        alpha.save()
        # Beta tag has a closed taxonomy
        beta = ObjectTag.objects.create(
            object_id="abc",
            taxonomy=self.taxonomy,
        )

        # Fetch all the tags for a given object ID
        assert list(
            tagging_api.get_object_tags(
                object_id="abc",
            )
        ) == [
            alpha,
            beta,
        ]

        # Fetch all the tags for a given object ID + taxonomy
        assert list(
            tagging_api.get_object_tags(
                object_id="abc",
                taxonomy_id=self.taxonomy.pk,
            )
        ) == [
            beta,
        ]

    @ddt.data(
        ("ChA", ["Archaea", "Archaebacteria"], [2, 5]),
        ("ar", ['Archaea', 'Archaebacteria', 'Arthropoda'], [2, 5, 14]),
        ("aE", ['Archaea', 'Archaebacteria', 'Plantae'], [2, 5, 10]),
        (
            "a",
            [
                'Animalia',
                'Archaea',
                'Archaebacteria',
                'Arthropoda',
                'Gastrotrich',
                'Monera',
                'Placozoa',
                'Plantae',
            ],
            [9, 2, 5, 14, 16, 13, 19, 10],
        ),
    )
    @ddt.unpack
    def test_autocomplete_tags(self, search: str, expected_values: list[str], expected_ids: list[int | None]) -> None:
        tags = [
            'Archaea',
            'Archaebacteria',
            'Animalia',
            'Arthropoda',
            'Plantae',
            'Monera',
            'Gastrotrich',
            'Placozoa',
        ] + expected_values  # To create repeats
        closed_taxonomy = self.taxonomy
        open_taxonomy = tagging_api.create_taxonomy(
            "Free_Text_Taxonomy",
            allow_free_text=True,
        )

        for index, value in enumerate(tags):
            # Creating ObjectTags for open taxonomy
            ObjectTag(
                object_id=f"object_id_{index}",
                taxonomy=open_taxonomy,
                _value=value,
            ).save()

            # Creating ObjectTags for closed taxonomy
            tag = get_tag(value)
            ObjectTag(
                object_id=f"object_id_{index}",
                taxonomy=closed_taxonomy,
                tag=tag,
                _value=value,
            ).save()

        # Test for open taxonomy
        self._validate_autocomplete_tags(
            open_taxonomy,
            search,
            expected_values,
            [None] * len(expected_ids),
        )

        # Test for closed taxonomy
        self._validate_autocomplete_tags(
            closed_taxonomy,
            search,
            expected_values,
            expected_ids,
        )

    def test_autocompleate_not_implemented(self) -> None:
        with self.assertRaises(NotImplementedError):
            tagging_api.autocomplete_tags(self.taxonomy, 'test', None, object_tags_only=False)

    def _get_tag_values(self, tags) -> list[str]:
        """
        Get tag values from tagging_api.autocomplete_tags() result
        """
        return [tag.get("value") for tag in tags]

    def _get_tag_ids(self, tags) -> list[int]:
        """
        Get tag ids from tagging_api.autocomplete_tags() result
        """
        return [tag.get("tag_id") for tag in tags]

    def _validate_autocomplete_tags(
        self,
        taxonomy: Taxonomy,
        search: str,
        expected_values: list[str],
        expected_ids: list[int | None],
    ) -> None:
        """
        Validate autocomplete tags
        """

        # Normal search
        result = tagging_api.autocomplete_tags(taxonomy, search)
        tag_values = self._get_tag_values(result)
        for value in tag_values:
            assert search.lower() in value.lower()

        assert tag_values == expected_values
        assert self._get_tag_ids(result) == expected_ids

        # Create ObjectTag to simulate the content tagging
        tag_model = None
        if not taxonomy.allow_free_text:
            tag_model = get_tag(tag_values[0])

        object_id = 'new_object_id'
        ObjectTag(
            object_id=object_id,
            taxonomy=taxonomy,
            tag=tag_model,
            _value=tag_values[0],
        ).save()

        # Search with object
        result = tagging_api.autocomplete_tags(taxonomy, search, object_id)
        assert self._get_tag_values(result) == expected_values[1:]
        assert self._get_tag_ids(result) == expected_ids[1:]