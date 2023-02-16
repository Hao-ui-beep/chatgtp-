# ext/index.py
# Copyright (C) 2005-2023 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: https://www.opensource.org/licenses/mit-license.php

"""Define attributes on ORM-mapped classes that have "index" attributes for
columns with :class:`_types.Indexable` types.

"index" means the attribute is associated with an element of an
:class:`_types.Indexable` column with the predefined index to access it.
The :class:`_types.Indexable` types include types such as
:class:`_types.ARRAY`, :class:`_types.JSON` and
:class:`_postgresql.HSTORE`.



The :mod:`~sqlalchemy.ext.indexable` extension provides
:class:`_schema.Column`-like interface for any element of an
:class:`_types.Indexable` typed column. In simple cases, it can be
treated as a :class:`_schema.Column` - mapped attribute.


.. versionadded:: 1.1

Synopsis
========

Given ``Person`` as a model with a primary key and JSON data field.
While this field may have any number of elements encoded within it,
we would like to refer to the element called ``name`` individually
as a dedicated attribute which behaves like a standalone column::

    from sqlalchemy import Column, JSON, Integer
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.ext.indexable import index_property

    Base = declarative_base()

    class Person(Base):
        __tablename__ = 'person'

        id = Column(Integer, primary_key=True)
        data = Column(JSON)

        name = index_property('data', 'name')


Above, the ``name`` attribute now behaves like a mapped column.   We
can compose a new ``Person`` and set the value of ``name``::

    >>> person = Person(name='Alchemist')

The value is now accessible::

    >>> person.name
    'Alchemist'

Behind the scenes, the JSON field was initialized to a new blank dictionary
and the field was set::

    >>> person.data
    {"name": "Alchemist'}

The field is mutable in place::

    >>> person.name = 'Renamed'
    >>> person.name
    'Renamed'
    >>> person.data
    {'name': 'Renamed'}

When using :class:`.index_property`, the change that we make to the indexable
structure is also automatically tracked as history; we no longer need
to use :class:`~.mutable.MutableDict` in order to track this change
for the unit of work.

Deletions work normally as well::

    >>> del person.name
    >>> person.data
    {}

Above, deletion of ``person.name`` deletes the value from the dictionary,
but not the dictionary itself.

A missing key will produce ``AttributeError``::

    >>> person = Person()
    >>> person.name
    ...
    AttributeError: 'name'

Unless you set a default value::

    >>> class Person(Base):
    >>>     __tablename__ = 'person'
    >>>
    >>>     id = Column(Integer, primary_key=True)
    >>>     data = Column(JSON)
    >>>
    >>>     name = index_property('data', 'name', default=None)  # See default

    >>> person = Person()
    >>> print(person.name)
    None


The attributes are also accessible at the class level.
Below, we illustrate ``Person.name`` used to generate
an indexed SQL criteria::

    >>> from sqlalchemy.orm import Session
    >>> session = Session()
    >>> query = session.query(Person).filter(Person.name == 'Alchemist')

The above query is equivalent to::

    >>> query = session.query(Person).filter(Person.data['name'] == 'Alchemist')

Multiple :class:`.index_property` objects can be chained to produce
multiple levels of indexing::

    from sqlalchemy import Column, JSON, Integer
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.ext.indexable import index_property

    Base = declarative_base()

    class Person(Base):
        __tablename__ = 'person'

        id = Column(Integer, primary_key=True)
        data = Column(JSON)

        birthday = index_property('data', 'birthday')
        year = index_property('birthday', 'year')
        month = index_property('birthday', 'month')
        day = index_property('birthday', 'day')

Above, a query such as::

    q = session.query(Person).filter(Person.year == '1980')

On a PostgreSQL backend, the above query will render as::

    SELECT person.id, person.data
    FROM person
    WHERE person.data -> %(data_1)s -> %(param_1)s = %(param_2)s

Default Values
==============

:class:`.index_property` includes special behaviors for when the indexed
data structure does not exist, and a set operation is called:

* For an :class:`.index_property` that is given an integer index value,
  the default data structure will be a Python list of ``None`` values,
  at least as long as the index value; the value is then set at its
  place in the list.  This means for an index value of zero, the list
  will be initialized to ``[None]`` before setting the given value,
  and for an index value of five, the list will be initialized to
  ``[None, None, None, None, None]`` before setting the fifth element
  to the given value.   Note that an existing list is **not** extended
  in place to receive a value.

* for an :class:`.index_property` that is given any other kind of index
  value (e.g. strings usually), a Python dictionary is used as the
  default data structure.

* The default data structure can be set to any Python callable using the
  :paramref:`.index_property.datatype` parameter, overriding the previous
  rules.


Subclassing
===========

:class:`.index_property` can be subclassed, in particular for the common
use case of providing coercion of values or SQL expressions as they are
accessed.  Below is a common recipe for use with a PostgreSQL JSON type,
where we want to also include automatic casting plus ``astext()``::

    class pg_json_property(index_property):
        def __init__(self, attr_name, index, cast_type):
            super(pg_json_property, self).__init__(attr_name, index)
            self.cast_type = cast_type

        def expr(self, model):
            expr = super(pg_json_property, self).expr(model)
            return expr.astext.cast(self.cast_type)

The above subclass can be used with the PostgreSQL-specific
version of :class:`_postgresql.JSON`::

    from sqlalchemy import Column, Integer
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.dialects.postgresql import JSON

    Base = declarative_base()

    class Person(Base):
        __tablename__ = 'person'

        id = Column(Integer, primary_key=True)
        data = Column(JSON)

        age = pg_json_property('data', 'age', Integer)

The ``age`` attribute at the instance level works as before; however
when rendering SQL, PostgreSQL's ``->>`` operator will be used
for indexed access, instead of the usual index operator of ``->``::

    >>> query = session.query(Person).filter(Person.age < 20)

The above query will render::

    SELECT person.id, person.data
    FROM person
    WHERE CAST(person.data ->> %(data_1)s AS INTEGER) < %(param_1)s

"""  # noqa
from __future__ import absolute_import

from .. import inspect
from .. import util
from ..ext.hybrid import hybrid_property
from ..orm.attributes import flag_modified


__all__ = ["index_property"]


class index_property(hybrid_property):  # noqa
    """A property generator. The generated property describes an object
    attribute that corresponds to an :class:`_types.Indexable`
    column.

    .. versionadded:: 1.1

    .. seealso::

        :mod:`sqlalchemy.ext.indexable`

    """

    _NO_DEFAULT_ARGUMENT = object()

    def __init__(
        self,
        attr_name,
        index,
        default=_NO_DEFAULT_ARGUMENT,
        datatype=None,
        mutable=True,
        onebased=True,
    ):
        """Create a new :class:`.index_property`.

        :param attr_name:
            An attribute name of an `Indexable` typed column, or other
            attribute that returns an indexable structure.
        :param index:
            The index to be used for getting and setting this value.  This
            should be the Python-side index value for integers.
        :param default:
            A value which will be returned instead of `AttributeError`
            when there is not a value at given index.
        :param datatype: default datatype to use when the field is empty.
            By default, this is derived from the type of index used; a
            Python list for an integer index, or a Python dictionary for
            any other style of index.   For a list, the list will be
            initialized to a list of None values that is at least
            ``index`` elements long.
        :param mutable: if False, writes and deletes to the attribute will
            be disallowed.
        :param onebased: assume the SQL representation of this value is
            one-based; that is, the first index in SQL is 1, not zero.
        """

        if mutable:
            super(index_property, self).__init__(
                self.fget, self.fset, self.fdel, self.expr
            )
        else:
            super(index_property, self).__init__(
                self.fget, None, None, self.expr
            )
        self.attr_name = attr_name
        self.index = index
        self.default = default
        is_numeric = isinstance(index, int)
        onebased = is_numeric and onebased

        if datatype is not None:
            self.datatype = datatype
        else:
            if is_numeric:
                self.datatype = lambda: [None for x in range(index + 1)]
            else:
                self.datatype = dict
        self.onebased = onebased

    def _fget_default(self, err=None):
        if self.default == self._NO_DEFAULT_ARGUMENT:
            util.raise_(AttributeError(self.attr_name), replace_context=err)
        else:
            return self.default

    def fget(self, instance):
        attr_name = self.attr_name
        column_value = getattr(instance, attr_name)
        if column_value is None:
            return self._fget_default()
        try:
            value = column_value[self.index]
        except (KeyError, IndexError) as err:
            return self._fget_default(err)
        else:
            return value

    def fset(self, instance, value):
        attr_name = self.attr_name
        column_value = getattr(instance, attr_name, None)
        if column_value is None:
            column_value = self.datatype()
            setattr(instance, attr_name, column_value)
        column_value[self.index] = value
        setattr(instance, attr_name, column_value)
        if attr_name in inspect(instance).mapper.attrs:
            flag_modified(instance, attr_name)

    def fdel(self, instance):
        attr_name = self.attr_name
        column_value = getattr(instance, attr_name)
        if column_value is None:
            raise AttributeError(self.attr_name)
        try:
            del column_value[self.index]
        except KeyError as err:
            util.raise_(AttributeError(self.attr_name), replace_context=err)
        else:
            setattr(instance, attr_name, column_value)
            flag_modified(instance, attr_name)

    def expr(self, model):
        column = getattr(model, self.attr_name)
        index = self.index
        if self.onebased:
            index += 1
        return column[index]
