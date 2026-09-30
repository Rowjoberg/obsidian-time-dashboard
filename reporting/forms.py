from django import forms

from reporting.services.reports import (
    ENTRY_SORT_CHOICES,
    GROUP_BY_CHOICES,
    PERIOD_CHOICES,
)


class FilterForm(forms.Form):
    period = forms.ChoiceField(choices=PERIOD_CHOICES, required=False)
    focus_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    group_by = forms.ChoiceField(choices=GROUP_BY_CHOICES, required=False)
    dynamic_filter_field = forms.ChoiceField(required=False)

    def __init__(
        self,
        *args,
        filter_definitions=None,
        filter_options=None,
        group_by_choices=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        filter_definitions = filter_definitions or []
        filter_options = filter_options or {}
        group_by_choices = group_by_choices or GROUP_BY_CHOICES

        self.fields["group_by"].choices = group_by_choices
        self.fields["dynamic_filter_field"].choices = [("", "Add frontmatter filter")] + [
            (definition["field_name"], definition["label"])
            for definition in filter_definitions
            if definition["source_type"] == "facet"
        ]

        self.dynamic_filter_fields = []
        self.base_filter_fields = []

        for definition in filter_definitions:
            choices = [(value, value) for value in filter_options.get(definition["form_field"], [])]
            self.fields[definition["form_field"]] = forms.MultipleChoiceField(
                required=False,
                choices=choices,
                widget=forms.SelectMultiple(
                    attrs={
                        "class": "ts-select",
                        "data-placeholder": definition["label"],
                        "data-filter-label": definition["label"],
                        "data-field-name": definition["field_name"],
                        "data-dynamic-filter": "true" if definition["dynamic"] else "false",
                        "data_field_name": definition["field_name"],
                        "data_dynamic_filter": "true" if definition["dynamic"] else "false",
                    }
                ),
                label=definition["label"],
            )
            if definition["dynamic"]:
                self.dynamic_filter_fields.append(self[definition["form_field"]])
            else:
                self.base_filter_fields.append(self[definition["form_field"]])


class EntryControlsForm(forms.Form):
    entry_search = forms.CharField(required=False)
    entry_sort = forms.ChoiceField(choices=ENTRY_SORT_CHOICES, required=False)


class WarningFilterForm(forms.Form):
    code = forms.ChoiceField(choices=[("", "All warning codes")], required=False)
    source_search = forms.CharField(required=False)
