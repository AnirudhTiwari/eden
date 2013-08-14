# -*- coding: utf-8 -*-

""" Framework for filtered REST requests

    @copyright: 2013 (c) Sahana Software Foundation
    @license: MIT

    @requires: U{B{I{gluon}} <http://web2py.com>}

    Permission is hereby granted, free of charge, to any person
    obtaining a copy of this software and associated documentation
    files (the "Software"), to deal in the Software without
    restriction, including without limitation the rights to use,
    copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following
    conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
    OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
    HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
    OTHER DEALINGS IN THE SOFTWARE.
"""

import re

try:
    import json # try stdlib (Python 2.6)
except ImportError:
    try:
        import simplejson as json # try external module
    except:
        import gluon.contrib.simplejson as json # fallback to pure-Python module

try:
    # Python 2.7
    from collections import OrderedDict
except:
    # Python 2.6
    from gluon.contrib.simplejson.ordered_dict import OrderedDict

from gluon import *
from gluon.sqlhtml import MultipleOptionsWidget
from gluon.storage import Storage
from gluon.tools import callback

from s3rest import S3Method
from s3resource import S3FieldSelector, S3ResourceField, S3URLQuery
from s3utils import s3_unicode
from s3validators import *
from s3widgets import S3DateWidget, S3DateTimeWidget, S3MultiSelectWidget, S3OrganisationHierarchyWidget, S3GroupedOptionsWidget, s3_grouped_checkboxes_widget

# =============================================================================
class S3FilterWidget(object):
    """ Filter widget for interactive search forms (base class) """

    #: the HTML class for the widget type
    _class = "generic-filter"

    #: the default query operator(s) for the widget type
    operator = None

    #: alternatives for client-side changeable operators
    alternatives = None

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Prototype method to render this widget as an instance of
            a web2py HTML helper class, to be implemented by subclasses.

            @param resource: the S3Resource to render with widget for
            @param values: the values for this widget from the URL query
        """

        raise NotImplementedError

    # -------------------------------------------------------------------------
    def variable(self, resource, get_vars=None):
        """
            Prototype method to generate the name for the URL query variable
            for this widget, can be overwritten in subclasses.

            @param resource: the resource
            @return: the URL query variable name (or list of
                     variable names if there are multiple operators)
        """

        label, self.selector = self._selector(resource, self.field)

        if not self.selector:
            return None

        if self.alternatives and get_vars is not None:
            # Get the actual operator from get_vars
            operator = self._operator(get_vars, self.selector)
            if operator:
                self.operator = operator

        if "label" not in self.opts:
            self.opts["label"] = label

        return self._variable(self.selector, self.operator)

    # -------------------------------------------------------------------------
    def data_element(self, variable):
        """
            Prototype method to construct the hidden element that holds the
            URL query term corresponding to an input element in the widget.

            @param variable: the URL query variable
        """

        if type(variable) is list:
            variable = "&".join(variable)
        return INPUT(_type="hidden",
                     _id="%s-data" % self.attr["_id"],
                     _class="filter-widget-data %s-data" % self._class,
                     _value=variable)

    # -------------------------------------------------------------------------
    # Helper methods
    #
    def __init__(self, field=None, **attr):
        """
            Constructor to configure the widget

            @param field: the selector(s) for the field(s) to filter by
            @param attr: configuration options for this widget
        """

        self.field = field
        self.alias = None

        attributes = Storage()
        options = Storage()
        for k, v in attr.iteritems():
            if k[0] == "_":
                attributes[k] = v
            else:
                options[k] = v
        self.attr = attributes
        self.opts = options

    # -------------------------------------------------------------------------
    def __call__(self, resource, get_vars=None, alias=None):
        """
            Entry point for the form builder

            @param resource: the S3Resource to render with widget for
            @param get_vars: the GET vars (URL query vars) to prepopulate
                             the widget
            @param alias: the resource alias to use
        """

        self.alias = alias

        # Initialize the widget attributes
        self._attr(resource)

        # Extract the URL values to populate the widget
        variable = self.variable(resource, get_vars)
        if type(variable) is list:
            values = Storage()
            for k in variable:
                values[k] = self._values(get_vars, k)
        else:
            values = self._values(get_vars, variable)

        # Construct and populate the widget
        widget = self.widget(resource, values)

        # Recompute variable in case operator got changed in widget()
        if self.alternatives:
            variable = self._variable(self.selector, self.operator)

        # Construct the hidden data element
        data = self.data_element(variable)

        if type(data) is list:
            data.append(widget)
        else:
            data = [data, widget]
        return TAG[""](*data)

    # -------------------------------------------------------------------------
    def _attr(self, resource):
        """ Initialize and return the HTML attributes for this widget """

        _class = self._class

        # Construct name and id for the widget
        attr = self.attr
        if "_name" not in attr:
            if not resource:
                raise SyntaxError("%s: _name parameter required " \
                                  "if rendered without resource." % \
                                  self.__class__.__name__)
            flist = self.field
            if type(flist) is not list:
                flist = [flist]
            colnames = []
            for f in flist:
                rfield = S3ResourceField(resource, f)
                colname = rfield.colname
                if colname:
                    colnames.append(colname)
                else:
                    colnames.append(rfield.fname)
            name = "%s-%s-%s" % (resource.alias, "-".join(colnames), _class)
            attr["_name"] = name.replace(".", "_")
        if "_id" not in attr:
            attr["_id"] = attr["_name"]

        return attr

    # -------------------------------------------------------------------------
    @classmethod
    def _operator(cls, get_vars, selector):
        """
            Helper method to get the operators from the URL query

            @param get_vars: the GET vars (a dict)
            @param selector: field selector

            @return: query operator - None, str or list
        """

        variables = ["%s__%s" % (selector, op) for op in cls.alternatives]
        slen = len(selector) + 2

        operators = [k[slen:] for k, v in get_vars.iteritems()
                                  if k in variables]
        if not operators:
            return None
        elif len(operators) == 1:
            return operators[0]
        else:
            return operators

    # -------------------------------------------------------------------------
    def _prefix(self, selector):
        """
            Helper method to prefix an unprefixed field selector

            @param alias: the resource alias to use as prefix
            @param selector: the field selector

            @return: the prefixed selector
        """

        alias = self.alias
        if alias is None:
            alias = "~"
        if "." not in selector.split("$", 1)[0]:
            return "%s.%s" % (alias, selector)
        else:
            return selector

    # -------------------------------------------------------------------------
    def _selector(self, resource, fields):
        """
            Helper method to generate a filter query selector for the
            given field(s) in the given resource.

            @param resource: the S3Resource
            @param fields: the field selectors (as strings)

            @return: the field label and the filter query selector, or None
                     if none of the field selectors could be resolved
        """

        prefix = self._prefix
        label = None

        if not fields:
            return label, None
        if not isinstance(fields, (list, tuple)):
            fields = [fields]
        selectors = []
        for field in fields:
            if resource:
                try:
                    rfield = S3ResourceField(resource, field)
                except (AttributeError, TypeError):
                    continue
                if not rfield.field and not rfield.virtual:
                    # Unresolvable selector
                    continue
                if not label:
                    label = rfield.label
                selectors.append(prefix(rfield.selector))
            else:
                selectors.append(field)
        if selectors:
            return label, "|".join(selectors)
        else:
            return label, None

    # -------------------------------------------------------------------------
    @staticmethod
    def _values(get_vars, variable):
        """
            Helper method to get all values of a URL query variable

            @param get_vars: the GET vars (a dict)
            @param variable: the name of the query variable

            @return: a list of values
        """

        if not variable:
            return []
        elif variable in get_vars:
            values = S3URLQuery.parse_value(get_vars[variable])
            if not isinstance(values, (list, tuple)):
                values = [values]
            return values
        else:
            return []

    # -------------------------------------------------------------------------
    @classmethod
    def _variable(cls, selector, operator):
        """
            Construct URL query variable(s) name from a filter query
            selector and the given operator(s)

            @param selector: the selector
            @param operator: the operator (or tuple/list of operators)

            @return: the URL query variable name (or list of variable names)
        """

        if isinstance(operator, (tuple, list)):
            return [cls._variable(selector, o) for o in operator]
        elif operator:
            return "%s__%s" % (selector, operator)
        else:
            return selector

# =============================================================================
class S3TextFilter(S3FilterWidget):

    _class = "text-filter"

    operator = "like"

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Render this widget as HTML helper object(s)

            @param resource: the resource
            @param values: the search values from the URL query
        """

        attr = self.attr

        if "_size" not in attr:
            attr.update(_size="40")
        if "_class" in attr and attr["_class"]:
            _class = "%s %s" % (attr["_class"], self._class)
        else:
            _class = self._class
        attr["_class"] = _class
        attr["_type"] = "text"

        values = [v.strip("*") for v in values if v is not None]
        if values:
            attr["_value"] = " ".join(values)

        return INPUT(**attr)

# =============================================================================
class S3RangeFilter(S3FilterWidget):
    """ Numerical Range Filter Widget """

    # Overall class
    _class = "range-filter"
    # Class for visible input boxes.
    _input_class = "%s-%s" % (_class, "input")

    operator = ["ge", "le"]

    # Untranslated labels for individual input boxes.
    input_labels = {"ge": "Minimum", "le": "Maximum"}

    # -------------------------------------------------------------------------
    def data_element(self, variables):
        """
            Overrides S3FilterWidget.data_element(), constructs multiple
            hidden INPUTs (one per variable) with element IDs of the form
            <id>-<operator>-data (where no operator is translated as "eq").

            @param variables: the variables
        """

        if variables is None:
            operators = self.operator
            if type(operators) is not list:
                operators = [operators]
            variables = self._variable(self.selector, operators)
        else:

            # Split the operators off the ends of the variables.
            if type(variables) is not list:
                variables = [variables]
            operators = [v.split("__")[1]
                         if "__" in v else "eq"
                         for v in variables]

        elements = []
        id = self.attr["_id"]

        for o, v in zip(operators, variables):

             elements.append(
                 INPUT(_type="hidden",
                       _id="%s-%s-data" % (id, o),
                       _class="filter-widget-data %s-data" % self._class,
                       _value=v))

        return elements

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Render this widget as HTML helper object(s)

            @param resource: the resource
            @param values: the search values from the URL query
        """

        attr = self.attr
        _class = self._class
        if "_class" in attr and attr["_class"]:
            _class = "%s %s" % (attr["_class"], _class)
        else:
            _class = _class
        attr["_class"] = _class

        input_class = self._input_class
        input_labels = self.input_labels
        input_elements = DIV()
        ie_append = input_elements.append

        selector = self.selector

        _variable = self._variable

        id = attr["_id"]
        for operator in self.operator:

            input_id = "%s-%s" % (id, operator)

            input_box = INPUT(_name=input_id,
                              _id=input_id,
                              _type="text",
                              _class=input_class)

            variable = _variable(selector, operator)

            # Populate with the value, if given
            # if user has not set any of the limits, we get [] in values.
            value = values.get(variable, None)
            if value not in [None, []]:
                if type(value) is list:
                    value = value[0]
                input_box["_value"] = value
                input_box["value"] = value

            ie_append(DIV(
                        DIV(LABEL(current.T(input_labels[operator] + ":"),
                                  _for=input_id),
                            _class="range-filter-label"),
                        DIV(input_box,
                            _class="range-filter-widget"),
                        _class="range-filter-field"))

        return input_elements

# =============================================================================
class S3DateFilter(S3RangeFilter):
    """ Date Range Filter Widget """

    _class = "date-filter"

    # Class for visible input boxes.
    _input_class = "%s-%s" % (_class, "input")

    operator = ["ge", "le"]

    # Untranslated labels for individual input boxes.
    input_labels = {"ge": "Earliest", "le": "Latest"}

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Render this widget as HTML helper object(s)

            @param resource: the resource
            @param values: the search values from the URL query
        """

        attr = self.attr

        # CSS class and element ID
        _class = self._class
        if "_class" in attr and attr["_class"]:
            _class = "%s %s" % (attr["_class"], _class)
        else:
            _class = _class
        _id = attr["_id"]

        # Determine the field type
        rfield = S3ResourceField(resource, self.field)
        field = rfield.field
        if rfield.virtual:
            # S3DateTimeWidget doesn't support virtual fields
            dtformat = current.deployment_settings.get_L10n_date_format()
            field = Field(rfield.fname, "datetime",
                          requires = IS_DATE_IN_RANGE(format = dtformat))
            field.tablename = field._tablename = rfield.tname
        elif not rfield.field:
            # Unresolvable selector
            return ""

        # Options
        hide_time = self.opts.get("hide_time", False)

        # Generate the input elements
        selector = self.selector
        _variable = self._variable
        input_class = self._input_class
        input_labels = self.input_labels
        input_elements = DIV(_id=_id, _class=_class)
        append = input_elements.append
        for operator in self.operator:

            input_id = "%s-%s" % (_id, operator)

            # Determine the widget class
            if rfield.ftype == "date":
                widget = S3DateWidget()
            else:
                opts = {}
                if operator == "ge":
                    opts["set_min"] = "%s-%s" % (_id, "le")
                elif operator == "le":
                    opts["set_max"] = "%s-%s" % (_id, "ge")
                widget = S3DateTimeWidget(hide_time=hide_time, **opts)

            # Populate with the value, if given
            # if user has not set any of the limits, we get [] in values.
            variable = _variable(selector, operator)
            value = values.get(variable, None)
            if value not in [None, []]:
                if type(value) is list:
                    value = value[0]
            else:
                value = None

            # Render the widget
            picker = widget(field, value,
                            _name=input_id,
                            _id=input_id,
                            _class=input_class)

            # Append label and widget
            append(DIV(
                    DIV(LABEL(current.T(input_labels[operator] + ":"),
                            _for=input_id),
                        _class="range-filter-label"),
                    DIV(picker,
                        _class="range-filter-widget"),
                    _class="range-filter-field"))

        return input_elements

# =============================================================================
class S3LocationFilter(S3FilterWidget):
    """ Hierarchical Location Filter Widget """

    _class = "location-filter"

    operator = "belongs"

    # -------------------------------------------------------------------------
    def __init__(self, field=None, **attr):
        """
            Constructor to configure the widget

            @param field: the selector(s) for the field(s) to filter by
            @param attr: configuration options for this widget
        """

        # Translate options using gis_location_name?
        settings = current.deployment_settings
        translate = settings.get_L10n_translate_gis_location()
        if translate:
            language = current.session.s3.language
            if language == settings.get_L10n_default_language():
                translate = False
        self.translate = translate

        super(S3LocationFilter, self).__init__(field=field, **attr)

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Render this widget as HTML helper object(s)

            @param resource: the resource
            @param values: the search values from the URL query
        """

        attr = self._attr(resource)
        opts = self.opts
        name = attr["_name"]

        ftype, levels, noopt = self._options(resource)
        if noopt:
            return SPAN(noopt, _class="no-options-available")

        # Filter class (default+custom)
        _class = self._class
        if "_class" in attr and attr["_class"]:
            _class = "%s %s" % (_class, attr["_class"])
        attr["_class"] = _class

        # Store id and name for the data element
        base_id = attr["_id"]
        base_name = attr["_name"]

        widgets = []
        w_append = widgets.append
        operator = self.operator
        field_name = self.field

        # @ToDo: Hide dropdowns other than first
        if opts.widget == "multiselect":

            # Multiselect Dropdown with Checkboxes
            if "multiselect-filter-widget" not in _class:
                attr["_class"] = "%s multiselect-filter-widget" % _class

            # Add one widget per level
            for level in levels:
                # Dummy field
                name = "%s-%s" % (base_name, level)
                options = levels[level]["options"]
                dummy_field = Storage(name=name,
                                      type=ftype,
                                      requires=IS_IN_SET(options,
                                                         multiple=True))
                # Unique ID/name
                attr["_id"] = "%s-%s" % (base_id, level)
                attr["_name"] = name
                # Find relevant values to pre-populate the widget
                _values = values["~.%s$%s__%s" % (field_name, level, operator)]
                w = S3MultiSelectWidget(filter = opts.get("filter", False),
                                        header = opts.get("header", False),
                                        selectedList = opts.get("selectedList", 3),
                                        noneSelectedText = "Select %s" % levels[level]["label"])
                widget = w(dummy_field, _values, **attr)
                w_append(widget)

        else:
            # Grouped Checkboxes
            if "s3-checkboxes-widget" not in _class:
                attr["_class"] = "%s s3-checkboxes-widget" % _class
            attr["cols"] = opts["cols"]

            # Add one widget per level
            for level in levels:
                # Dummy field
                name = "%s-%s" % (base_name, level)
                options = levels[level]["options"]
                dummy_field = Storage(name=name,
                                      type=ftype,
                                      requires=IS_IN_SET(options,
                                                         multiple=True))
                # Unique ID/name
                attr["_id"] = "%s-%s" % (base_id, level)
                attr["_name"] = name
                # Find relevant values to pre-populate
                _values = values["~.%s$%s__%s" % (field_name, level, operator)]
                w_append(s3_grouped_checkboxes_widget(dummy_field,
                                                      _values,
                                                      **attr))

        # Restore id and name for the data_element
        attr["_id"] = base_id
        attr["_name"] = base_name

        # Render the filter widget
        return TAG[""](*widgets)

    # -------------------------------------------------------------------------
    def data_element(self, variable):
        """
            Construct the hidden element that holds the
            URL query term corresponding to an input element in the widget.

            @param variable: the URL query variable
        """

        output = []
        oappend = output.append
        i = 0
        for level in self.levels:
            widget = INPUT(_type="hidden",
                           _id="%s-%s-data" % (self.attr["_id"], level),
                           _class="filter-widget-data %s-data" % self._class,
                           _value=variable[i])
            oappend(widget)
            i += 1

        return output

    # -------------------------------------------------------------------------
    def ajax_options(self, resource):

        attr = self._attr(resource)
        ftype, levels, noopt = self._options(resource, inject_hierarchy=False)

        opts = {}
        base_id = attr["_id"]
        for level in levels:
            if noopt:
                opts["%s-%s" % (base_id, level)] = str(noopt)
            else:
                options = levels[level]["options"]
                opts["%s-%s" % (base_id, level)] = options
        return opts

    # -------------------------------------------------------------------------
    def _options(self, resource, inject_hierarchy=True):

        T = current.T

        NOOPT = T("No options available")

        attr = self.attr
        opts = self.opts
        translate = self.translate

        # Which levels should we display?
        # Lookup the appropriate labels from the GIS configuration
        hierarchy = current.gis.get_location_hierarchy()
        levels = OrderedDict()
        if "levels" in opts:
            for level in opts["levels"]:
                levels[level] = hierarchy.get(level, level)
        else:
            # @ToDo: Do this dynamically from the data?
            for level in hierarchy:
                levels[level] = hierarchy.get(level, level)
        # Pass to data_element
        self.levels = levels

        if "label" not in opts:
            opts["label"] = T("Filter by Location")

        ftype = "reference gis_location"
        default = (ftype, levels.keys(), opts.get("no_opts", NOOPT))

        # Resolve the field selector
        field_name = self.field
        rfield = S3ResourceField(resource, field_name)
        field = rfield.field
        if not field or rfield.ftype[:len(ftype)] != ftype:
            # Must be a real reference to gis_location
            return default
        fields = [field_name] + ["%s$%s" % (field_name, l) for l in levels]
        if translate:
            fields += ["%s$path" % field_name]
    
        # Find the options
        rows = resource.select(fields=fields,
                               limit=None,
                               virtual=False,
                               as_rows=True)
        # No options?
        if not rows:
            return default

        # Initialise Options Storage & Hierarchy
        hierarchy = {}
        first = True
        for level in levels:
            if first:
                hierarchy[level] = {}
                _level = level
                first = False
            # @ToDo: Translate Labels
            levels[level] = {"label": levels[level],
                             "options": {} if translate else [],
                             }

        # Build the options & hierarchy
        if translate:
            # Get IDs via Path to lookup name_l10n
            ids = []
            iappend = ids.append
            for row in rows:
                if "gis_location" in row:
                    path = row.gis_location.path.split("/")
                    for id in path:
                        if id not in ids:
                            iappend(id)
            # Build lookup table for name_l10n
            name_l10n = {}
            s3db = current.s3db
            table = s3db.gis_location
            ntable = s3db.gis_location_name
            query = (table.id.belongs(ids)) & \
                    (ntable.deleted == False) & \
                    (ntable.location_id == table.id) & \
                    (ntable.language == current.session.s3.language)
            nrows = current.db(query).select(table.name,
                                             ntable.name_l10n,
                                             limitby=(0, len(ids)),
                                             )
            for row in nrows:
                name_l10n[row["gis_location.name"]] = row["gis_location_name.name_l10n"]

        # Populate the Options and the Hierarchy
        for row in rows:
            if "gis_location" in row:
                _row = row.gis_location
                if inject_hierarchy:
                    parent = None
                    grandparent = None
                    greatgrandparent = None
                    greatgreatgrandparent = None
                    greatgreatgreatgrandparent = None
                    i = 0
                for level in levels:
                    v = _row[level]
                    if v:
                        o = levels[level]["options"]
                        if v not in o:
                            if translate:
                                o[v] = name_l10n.get(v, v)
                            else:
                                o.append(v)
                    if inject_hierarchy:
                        if i == 0:
                            h = hierarchy[_level]
                            if v not in h:
                                h[v] = {}
                            parent = v
                        elif i == 1:
                            h = hierarchy[_level][parent]
                            if v not in h:
                                h[v] = {}
                            grandparent = parent
                            parent = v
                        elif i == 2:
                            h = hierarchy[_level][grandparent][parent]
                            if v not in h:
                                h[v] = {}
                            greatgrandparent = grandparent
                            grandparent = parent
                            parent = v
                        elif i == 3:
                            h = hierarchy[_level][greatgrandparent][grandparent][parent]
                            if v not in h:
                                h[v] = {}
                            greatgreatgrandparent = greatgrandparent
                            greatgrandparent = grandparent
                            grandparent = parent
                            parent = v
                        elif i == 4:
                            h = hierarchy[_level][greatgreatgrandparent][greatgrandparent][grandparent][parent]
                            if v not in h:
                                h[v] = {}
                            greatgreatgreatgrandparent = greatgreatgrandparent
                            greatgreatgrandparent = greatgrandparent
                            greatgrandparent = grandparent
                            grandparent = parent
                            parent = v
                        elif i == 5:
                            h = hierarchy[_level][greatgreatgreatgrandparent][greatgreatgrandparent][greatgrandparent][grandparent][parent]
                            if v not in h:
                                h[v] = {}
                        i += 1
        if translate:
            # Sort the options dicts
            for level in levels:
                options = levels[level]["options"]
                options = OrderedDict(sorted(options.iteritems()))
        else:
            # Sort the options lists
            for level in levels:
                levels[level]["options"].sort()

        if inject_hierarchy:
            # Inject the Location Hierarchy
            hierarchy = "S3.location_filter_hierarchy=%s" % json.dumps(hierarchy)
            js_global = current.response.s3.js_global
            js_global.append(hierarchy)
            if translate:
                # Inject lookup list
                name_l10n = "S3.location_name_l10n=%s" % json.dumps(name_l10n)
                js_global.append(name_l10n)

        return (ftype, levels, None)

    # -------------------------------------------------------------------------
    def _selector(self, resource, fields):
        """
            Helper method to generate a filter query selector for the
            given field(s) in the given resource.

            @param resource: the S3Resource
            @param fields: the field selectors (as strings)

            @return: the field label and the filter query selector, or None if none of the
                     field selectors could be resolved
        """

        prefix = self._prefix
        label = None

        if "levels" in self.opts:
            levels = self.opts.levels
        else:
            levels = current.gis.hierarchy_level_keys
        fields = ["%s$%s" % (fields, level) for level in levels]
        selectors = []
        for field in fields:
            try:
                rfield = S3ResourceField(resource, field)
            except (AttributeError, TypeError):
                continue
            if not label:
                label = rfield.label
            selectors.append(prefix(rfield.selector))
        if selectors:
            return label, "|".join(selectors)
        else:
            return label, None

    # -------------------------------------------------------------------------
    @classmethod
    def _variable(cls, selector, operator):
        """
            Construct URL query variable(s) name from a filter query
            selector and the given operator(s)

            @param selector: the selector
            @param operator: the operator (or tuple/list of operators)

            @return: the URL query variable name (or list of variable names)
        """

        selectors = selector.split("|")
        return ["%s__%s" % (selector, operator) for selector in selectors]

# =============================================================================
class S3OptionsFilter(S3FilterWidget):

    _class = "options-filter"

    operator = "belongs"

    alternatives = ["anyof", "contains"]

    # -------------------------------------------------------------------------
    def widget(self, resource, values):
        """
            Render this widget as HTML helper object(s)

            @param resource: the resource
            @param values: the search values from the URL query
        """

        attr = self._attr(resource)
        opts = self.opts
        name = attr["_name"]

        # Filter class (default+custom)
        _class = self._class
        if "_class" in attr and attr["_class"]:
            _class = "%s %s" % (_class, attr["_class"])
        attr["_class"] = _class

        # Get the options
        ftype, options, noopt = self._options(resource)
        if noopt:
            return SPAN(noopt, _class="no-options-available")
        else:
            options = OrderedDict(options)

        # Any-All-Option : for many-to-many fields the user can
        # search for records containing all the options or any
        # of the options:
        if len(options) > 1 and ftype[:4] == "list":
            if self.operator == "anyof":
                filter_type = "any"
            else:
                filter_type = "all"
                if self.operator == "belongs":
                    self.operator = "contains"

            T = current.T
            any_all = DIV(T("Filter type"),
                          INPUT(_name="%s_filter" % name,
                                _id="%s_filter_any" % name,
                                _type="radio",
                                _value="any",
                                value=filter_type),
                          LABEL(T("Any"),
                                _for="%s_filter_any" % name),
                          INPUT(_name="%s_filter" % name,
                                _id="%s_filter_all" % name,
                                _type="radio",
                                _value="all",
                                value=filter_type),
                          LABEL(T("All"),
                                _for="%s_filter_all" % name),
                          _class="s3-options-filter-anyall")
        else:
            any_all = ""

        # Render the filter widget
        dummy_field = Storage(name=name,
                              type=ftype,
                              requires=IS_IN_SET(options, multiple=True))

        widget_type = opts["widget"]
        if widget_type == "multiselect-bootstrap":
            script = "/%s/static/scripts/bootstrap-multiselect.js" % \
                        current.request.application
            scripts = current.response.s3.scripts
            if script not in scripts:
                scripts.append(script)
            widget = MultipleOptionsWidget.widget(dummy_field,
                                                  values,
                                                  **attr)
            widget.add_class("multiselect-filter-bootstrap")
        elif widget_type == "multiselect":
            if "multiselect-filter-widget" not in _class:
                attr["_class"] = "%s multiselect-filter-widget" % _class
            w = S3MultiSelectWidget(filter = opts.get("filter", False),
                                    header = opts.get("header", False),
                                    selectedList = opts.get("selectedList", 3),
                                    )
            widget = w(dummy_field, values, **attr)
        else:
            if "groupedopts-filter-widget" not in _class:
                attr["_class"] = "%s groupedopts-filter-widget" % _class
            w = S3GroupedOptionsWidget(
                    options = options,
                    multiple = True,
                    cols = opts["cols"],
                    size = opts["size"] or 12,
                    help_field = opts["help_field"],
                )
            widget = w(dummy_field, values, **attr)

        return TAG[""](any_all, widget)

    # -------------------------------------------------------------------------
    def ajax_options(self, resource):
        """
            Method to Ajax-retrieve the current options of this widget

            @param resource: the S3Resource
        """

        opts = self.opts
        attr = self._attr(resource)
        ftype, options, noopt = self._options(resource)

        if noopt:
            options = {attr["_id"]: str(noopt)}
        else:
            widget_type = opts["widget"]
            if widget_type in ("multiselect-bootstrap", "multiselect"):
                # Produce a simple list of tuples
                options = {attr["_id"]: [(k, s3_unicode(v))
                                         for k, v in options]}
            else:
                # Use the widget method to group and sort the options
                widget = S3GroupedOptionsWidget(
                                options = options,
                                multiple = True,
                                cols = opts["cols"],
                                size = opts["size"] or 12,
                                help_field = opts["help_field"])
                options = {attr["_id"]:
                           widget._options({"type": ftype}, [])}
        return options
        
    # -------------------------------------------------------------------------
    def _options(self, resource):
        """
            Helper function to retrieve the current options for this
            filter widget

            @param resource: the S3Resource
        """

        T = current.T
        NOOPT = T("No options available")
        EMPTY = T("None")

        attr = self.attr
        opts = self.opts

        # Resolve the field selector
        selector = self.field
        if isinstance(selector, (tuple, list)):
            selector = selector[0]

        rfield = S3ResourceField(resource, selector)
        field = rfield.field
        colname = rfield.colname
        ftype = rfield.ftype

        # Find the options

        if opts.options is not None:
            # Custom dict of options {value: label} or a callable
            # returning such a dict:
            options = opts.options
            if callable(options):
                options = options()
            opt_keys = options.keys()

        else:
            # Determine the options from the field type
            options = None
            if ftype == "boolean":
                opt_keys = (True, False)

            elif field or rfield.virtual:
                multiple = ftype[:5] == "list:"
                groupby = field if field and not multiple else None
                virtual = field is None
                rows = resource.select([selector],
                                       limit=None,
                                       orderby=field,
                                       groupby=groupby,
                                       virtual=virtual,
                                       as_rows=True)
                opt_keys = []
                if rows:
                    if multiple:
                        kextend = opt_keys.extend
                        for row in rows:
                            vals = row[colname]
                            if vals:
                                kextend([v for v in vals
                                           if v not in opt_keys])
                    else:
                        kappend = opt_keys.append
                        for row in rows:
                            v = row[colname]
                            if v not in opt_keys:
                                kappend(v)
            else:
                opt_keys = []

        # No options?
        if len(opt_keys) < 1 or len(opt_keys) == 1 and not opt_keys[0]:
            return (ftype, None, opts.get("no_opts", NOOPT))

        # Represent the options

        opt_list = [] # list of tuples (key, value)

        # Custom represent? (otherwise fall back to field represent)
        represent = opts.represent
        if not represent or ftype[:9] != "reference":
            represent = field.represent

        if options is not None:
            # Custom dict of {value:label} => use this label
            opt_list = options.items()

        elif callable(represent):
            # Callable representation function:

            if hasattr(represent, "bulk"):
                # S3Represent => use bulk option
                opt_dict = represent.bulk(opt_keys,
                                          list_type=False,
                                          show_link=False)
                if None in opt_keys:
                    opt_dict[None] = EMPTY
                elif None in opt_dict:
                    del opt_dict[None]
                if "" in opt_keys:
                    opt_dict[""] = EMPTY
                opt_list = opt_dict.items()

            else:
                # Simple represent function
                args = {"show_link": False} \
                       if "show_link" in represent.func_code.co_varnames else {}
                if multiple:
                    repr_opt = lambda opt: opt in (None, "") and (opt, EMPTY) or \
                                           (opt, represent([opt], **args))
                else:
                    repr_opt = lambda opt: opt in (None, "") and (opt, EMPTY) or \
                                           (opt, represent(opt, **args))
                opt_list = map(repr_opt, opt_keys)

        elif isinstance(represent, str) and ftype[:9] == "reference":
            # Represent is a string template to be fed from the
            # referenced record

            # Get the referenced table
            db = current.db
            ktable = db[ftype[10:]]

            k_id = ktable._id.name

            # Get the fields referenced by the string template
            fieldnames = [k_id]
            fieldnames += re.findall("%\(([a-zA-Z0-9_]*)\)s", represent)
            represent_fields = [ktable[fieldname] for fieldname in fieldnames]

            # Get the referenced records
            query = (ktable.id.belongs([k for k in opt_keys
                                              if str(k).isdigit()])) & \
                    (ktable.deleted == False)
            rows = db(query).select(*represent_fields).as_dict(key=k_id)

            # Run all referenced records against the format string
            opt_list = []
            ol_append = opt_list.append
            for opt_value in opt_keys:
                if opt_value in rows:
                    opt_represent = represent % rows[opt_value]
                    if opt_represent:
                        ol_append((opt_value, opt_represent))

        else:
            # Straight string representations of the values (fallback)
            opt_list = [(opt_value, s3_unicode(opt_value))
                        for opt_value in opt_keys if opt_value]

        none = opts["none"]
        opt_list.sort(key = lambda item: item[1])
        options = []
        empty = None
        for k, v in opt_list:
            if k is None:
                empty = ("NONE", v)
            else:
                options.append((k, v))
        if empty and none:
            options.append(empty)

        # Sort the options
        return (ftype, options, None)

# =============================================================================
class S3FilterForm(object):
    """ Helper class to construct and render a filter form for a resource """

    def __init__(self, widgets, **attr):
        """
            Constructor

            @param widgets: the widgets (as list)
            @param attr: HTML attributes for this form
        """

        self.widgets = widgets

        attributes = Storage()
        options = Storage()
        for k, v in attr.iteritems():
            if k[0] == "_":
                attributes[k] = v
            else:
                options[k] = v
        self.attr = attributes
        self.opts = options

    # -------------------------------------------------------------------------
    def html(self, resource, get_vars=None, target=None, alias=None):
        """
            Render this filter form as HTML form.

            @param resource: the S3Resource
            @param get_vars: the request GET vars (URL query dict)
            @param target: the HTML element ID of the target object for
                           this filter form (e.g. a datatable)
            @param alias: the resource alias to use in widgets
        """

        attr = self.attr
        form_id = attr.get("_id")
        if not form_id:
            form_id = "filter-form"
        attr["_id"] = form_id

        opts = self.opts
        formstyle = opts.get("formstyle", None)
        if not formstyle:
            formstyle = self._formstyle

        # Filter Manager (load/apply/save filters)
        rows = []
        fm = current.deployment_settings.get_search_filter_manager()
        if fm and opts.get("filter_manager", True):
            filter_manager = self._render_filters(resource, form_id)
            if filter_manager:
                rows = [formstyle(None, "", filter_manager, "")]

        # Filter widgets
        rows.extend(self._render_widgets(resource,
                                         get_vars=get_vars or {},
                                         alias=alias,
                                         formstyle=formstyle))

        # Other filter form controls
        controls = self._render_controls()
        if controls:
            rows.append(formstyle(None, "", controls, ""))

        # Submit button
        submit = opts.get("submit", False)
        if submit:
            _class = "filter-submit"
            ajax = opts.get("ajax", False)
            if ajax:
                _class = "%s filter-ajax" % _class
            if submit is True:
                label = current.T("Search")
            elif isinstance(submit, (list, tuple)):
                label = submit[0]
                _class = "%s %s" % (submit[1], _class)
            else:
                label = submit
            # Where to request filtered data from:
            submit_url = opts.get("url", URL(vars={}))
            # Where to request updated options from:
            ajax_url = opts.get("ajaxurl", URL(args=["filter.options"], vars={}))
            submit = TAG[""](
                        INPUT(_type="button",
                              _value=label,
                              _class=_class),
                        INPUT(_type="hidden",
                              _class="filter-ajax-url",
                              _value=ajax_url),
                        INPUT(_type="hidden",
                              _class="filter-submit-url",
                              _value=submit_url))

            if ajax and target:
                submit.append(INPUT(_type="hidden",
                                    _class="filter-submit-target",
                                    _value=target))

            rows.append(formstyle(None, "", submit, ""))

        # Adapt to formstyle: render a TABLE only if formstyle returns TRs
        if rows:
            elements = rows[0]
            if not isinstance(elements, (list, tuple)):
                elements = elements.elements()
            n = len(elements)
            if n > 0 and elements[0].tag == "tr" or \
               n > 1 and elements[0].tag == "" and elements[1].tag == "tr":
                form = FORM(TABLE(TBODY(rows)), **attr)
            else:
                form = FORM(DIV(rows), **attr)
            form.add_class("filter-form")

        # Put a copy of formstyle into the form for access by the view
        form.formstyle = formstyle
        return form

    # -------------------------------------------------------------------------
    def fields(self, resource, get_vars=None, alias=None):
        """
            Render the filter widgets without FORM wrapper, e.g. to
            embed them as fieldset in another form.

            @param resource: the S3Resource
            @param get_vars: the request GET vars (URL query dict)
            @param alias: the resource alias to use in widgets
        """

        formstyle = self.opts.get("formstyle", None)
        if not formstyle:
            formstyle = self._formstyle

        rows = self._render_widgets(resource,
                                    get_vars=get_vars,
                                    alias=alias,
                                    formstyle=formstyle)

        controls = self._render_controls()
        if controls:
            rows.append(formstyle(None, "", controls, ""))
        
        # Adapt to formstyle: only render a TABLE if formstyle returns TRs
        if rows:
            elements = rows[0]
            if not isinstance(elements, (list, tuple)):
                elements = elements.elements()
            n = len(elements)
            if n > 0 and elements[0].tag == "tr" or \
               n > 1 and elements[0].tag == "" and elements[1].tag == "tr":
                fields = TABLE(TBODY(rows))
            else:
                fields = DIV(rows)

        return fields

    # -------------------------------------------------------------------------
    def _render_controls(self):
        """
            Render optional additional filter form controls: advanced
            options toggle, clear filters.
        """

        controls = []
    
        advanced = self.opts.get("advanced", False)
        if advanced:
            _class = "filter-advanced"
            T = current.T
            if advanced is True:
                label = T("More Options")
            elif isinstance(advanced, (list, tuple)):
                label = advanced[0]
                label = advanced[1]
                if len(advanced > 2):
                    _class = "%s %s" % (advanced[2], _class)
            else:
                label = advanced
            label_off = T("Less Options")
            advanced = INPUT(_type="button",
                             _value=label,
                             _label_on=label,
                             _label_off=label_off,
                             _class=_class)
            controls.append(advanced)

        clear = self.opts.get("clear", True)
        if clear:
            _class = "filter-clear"
            if clear is True:
                label = current.T("Reset filter")
            elif isinstance(clear, (list, tuple)):
                label = clear[0]
                _class = "%s %s" % (clear[1], _class)
            else:
                label = clear
            clear = A(label, _class=_class)
            clear.add_class("action-lnk")
            controls.append(clear)

        if controls:
            return DIV(controls, _class="filter-controls")
        else:
            return None

    # -------------------------------------------------------------------------
    def _render_widgets(self,
                        resource,
                        get_vars=None,
                        alias=None,
                        formstyle=None):
        """
            Render the filter widgets
    
            @param resource: the S3Resource
            @param get_vars: the request GET vars (URL query dict)
            @param alias: the resource alias to use in widgets
            @param formstyle: the formstyle to use

            @return: a list of form rows
        """
        
        rows = []
        rappend = rows.append
        advanced = False
        for f in self.widgets:
            widget = f(resource, get_vars, alias=alias)
            label = f.opts["label"]
            comment = f.opts["comment"]
            hidden = f.opts["hidden"]
            if hidden:
                advanced = True
            widget_id = f.attr["_id"]
            if widget_id:
                row_id = "%s__row" % widget_id
                label_id = "%s__label" % widget_id
            else:
                row_id = None
                label_id = None
            if label:
                label = LABEL("%s :" % label, _id=label_id, _for=widget_id)
            else:
                label = ""
            if not comment:
                comment = ""
            rappend(formstyle(row_id, label, widget, comment, hidden=hidden))
        if advanced:
            self.opts["advanced"] = resource.get_config("filter_advanced", True)
        return rows
            
    # -------------------------------------------------------------------------
    def _render_filters(self, resource, form_id):
        """
            Render a filter manager widget

            @param resource: the resource
            @return: the widget
        """

        SELECT_FILTER = current.T("Saved Filters...")

        ajaxurl = self.opts.get("saveurl", URL(args=["filter.json"], vars={}))
        
        # Current user
        auth = current.auth
        pe_id = auth.user.pe_id if auth.s3_logged_in() else None
        if not pe_id:
            return None
    
        table = current.s3db.pr_filter
        query = (table.deleted != True) & \
                (table.pe_id == pe_id) & \
                (table.resource == resource.tablename)

        rows = current.db(query).select(table._id,
                                        table.title,
                                        table.query,
                                        orderby=table.title)
                                        
        options = [OPTION(SELECT_FILTER,
                          _value="",
                          _class="filter-manager-prompt",
                          _disabled="disabled")]
        add_option = options.append
        filters = {}
        for row in rows:
            filter_id = row[table._id]
            add_option(OPTION(row.title, _value=filter_id))
            query = row.query
            if query:
                query = json.loads(query)
            filters[filter_id] = query
        widget_id = "%s-fm" % form_id
        widget = SELECT(options,
                        _id=widget_id,
                        _class="filter-manager-widget")

        T = current.T
        script = """
$("#%(widget_id)s").filtermanager({
  filters: %(filters)s,
  ajaxURL: "%(ajaxurl)s",
  saveTooltip: "%(save_tooltip)s",
  loadTooltip: "%(load_tooltip)s",
  createTooltip: "%(create_tooltip)s",
  titleHint: "%(title_hint)s",
  selectHint: "%(select_hint)s",
  emptyHint: "%(empty_hint)s",
  confirmUpdate: true,
  confirmText: "%(confirm_text)s"
})""" % dict(
            widget_id = widget_id,
            filters = json.dumps(filters),
            ajaxurl = ajaxurl,
            save_tooltip = T("Update saved filter"),
            load_tooltip = T("Load filter"),
            create_tooltip = T("Create new filter from current options"),
            title_hint = T("Enter a title..."),
            select_hint = SELECT_FILTER,
            empty_hint = T("No saved filters"),
            confirm_text = T("Update this filter?"),
        )
        current.response.s3.jquery_ready.append(script)

        return widget

    # -------------------------------------------------------------------------
    def json(self, resource, get_vars=None):
        """
            Render this filter form as JSON (for Ajax requests)

            @param resource: the S3Resource
            @param get_vars: the request GET vars (URL query dict)
        """

        raise NotImplementedError

    # -------------------------------------------------------------------------
    @staticmethod
    def _formstyle(row_id, label, widget, comment, hidden=False):
        """
            Default formstyle for search forms

            @param row_id: HTML id for the row
            @param label: the label
            @param widget: the form widget
            @param comment: the comment
            @param hidden: whether the row should initially be hidden or not
        """

        if hidden:
            _class = "advanced hide"
        else:
            _class = ""

        row = TR(TD(label, _class="w2p_fl"), TD(widget),
                 _id=row_id, _class=_class)

        if comment:
            row.append(TD(DIV(_class="tooltip",
                              _title="%s|%s" % (label, comment)),
                          _class="w2p_fc"))
        return row

# =============================================================================
class S3Filter(S3Method):
    """ Back-end for filter form updates """

    def apply_method(self, r, **attr):
        """
            Entry point for REST interface

            @param r: the S3Request
            @param attr: additional controller parameters
        """

        representation = r.representation
        if representation == "options":
            # Return the filter options as JSON
            return self._options(r, **attr)

        elif representation == "json":
            if r.http == "GET":
                # Load list of saved filters
                return self._load(r, **attr)
            elif r.http == "POST":
                # Save a filter
                return self._save(r, **attr)
            else:
                r.error(405, r.ERROR.BAD_METHOD)
                
        elif representation == "html":
            return self._form(r, **attr)

        else:
            r.error(501, r.ERROR.BAD_FORMAT)

    # -------------------------------------------------------------------------
    def _form(self, r, **attr):
        """
            Get the filter form for the target resource as HTML snippet

            GET filter.html

            @param r: the S3Request
            @param attr: additional controller parameters
        """

        r.error(501, r.ERROR.NOT_IMPLEMENTED)

    # -------------------------------------------------------------------------
    def _options(self, r, **attr):
        """
            Get the updated options for the filter form for the target
            resource as JSON

            GET filter.options

            @param r: the S3Request
            @param attr: additional controller parameters
        """

        resource = self.resource
        get_config = resource.get_config

        options = {}

        filter_widgets = get_config("filter_widgets", None)
        if filter_widgets:
            fresource = current.s3db.resource(resource.tablename)

            for widget in filter_widgets:
                if hasattr(widget, "ajax_options"):
                    opts = widget.ajax_options(fresource)
                    if opts and isinstance(opts, dict):
                        options.update(opts)

        options = json.dumps(options)
        current.response.headers["Content-Type"] = "application/json"
        return options

    # -------------------------------------------------------------------------
    def _save(self, r, **attr):
        """
            Save a filter

            POST filter.json
            
            @param r: the S3Request
            @param attr: additional controller parameters
        """

        # Authorization, get pe_id
        auth = current.auth
        if auth.s3_logged_in():
            pe_id = current.auth.user.pe_id
        else:
            pe_id = None
        if not pe_id:
            r.unauthorised()

        # Read the source
        source = r.body
        source.seek(0)

        try:
            data = json.load(source)
        except ValueError:
            r.error(501, r.ERROR.BAD_SOURCE)

        # Try to find the record
        db = current.db
        s3db = current.s3db
        
        table = s3db.pr_filter
        record_id = data.get("id")
        record = None
        if record_id:
            query = (table.id == record_id) & (table.pe_id == pe_id)
            record = db(query).select(table.id, limitby=(0, 1)).first()
            if not record:
                r.error(404, r.ERROR.BAD_RECORD)

        # Build new record
        filter_data = {
            "pe_id": pe_id,
            "controller": r.controller,
            "function": r.function,
            "resource": self.resource.tablename,
            "deleted": False,
        }

        title = data.get("title")
        if title is not None:
            filter_data["title"] = title

        description = data.get("description")
        if description is not None:
            filter_data["description"] = description

        query = data.get("query")
        if query is not None:
            filter_data["query"] = json.dumps(query)

        # Store record
        onaccept = None
        if record:
            success = db(table.id == record_id).update(**filter_data)
            if success:
                info = {"updated": record_id}
                onaccept = s3db.get_config(table, "update_onaccept",
                           s3db.get_config(table, "onaccept"))
        else:
            success = table.insert(**filter_data)
            if success:
                record_id = success
                info = {"created": record_id}
                onaccept = s3db.get_config(table, "update_onaccept",
                           s3db.get_config(table, "onaccept"))

        if onaccept is not None:
            filter_data["id"] = record_id
            callback(onaccept, Storage(vars=filter_data))

        # Success/Error response
        xml = current.xml
        if success:
            msg = xml.json_message(**info)
        else:
            msg = xml.json_message(False, 400)
        current.response.headers["Content-Type"] = "application/json"
        return msg

    # -------------------------------------------------------------------------
    def _load(self, r, **attr):
        """
            Load filters

            GET filter.json or GET filter.json?load=<id>
            
            @param r: the S3Request
            @param attr: additional controller parameters
        """

        db = current.db
        table = current.s3db.pr_filter

        # Authorization, get pe_id
        auth = current.auth
        if auth.s3_logged_in():
            pe_id = current.auth.user.pe_id
        else:
            pe_id = None
        if not pe_id:
            r.unauthorized()

        # Build query
        query = (table.deleted != True) & \
                (table.resource == self.resource.tablename) & \
                (table.pe_id == pe_id)

        # Any particular filters?
        load = r.get_vars.get("load")
        if load:
            record_ids = [i for i in load.split(",") if i.isdigit()]
            if record_ids:
                if len(record_ids) > 1:
                    query &= table.id.belongs(record_ids)
                else:
                    query &= table.id == record_ids[0]
        else:
            record_ids = None

        # Retrieve filters
        rows = db(query).select(table.id,
                                table.title,
                                table.description,
                                table.query)

        # Pack filters
        filters = []
        for row in rows:
            filters.append({
                "id": row.id,
                "title": row.title,
                "description": row.description,
                "query": json.loads(row.query) if row.query else [],
            })

        # JSON response
        current.response.headers["Content-Type"] = "application/json"
        return json.dumps(filters)

# END =========================================================================
