"""Objects for implementing DBs and DB objects."""

__author__ = "Tom Goetz"
__copyright__ = "Copyright Tom Goetz"
__license__ = "GPL"

import logging
import datetime

from sqlalchemy import func, desc, extract, and_, literal_column
from sqlalchemy.orm import synonym, Query
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm.attributes import set_attribute
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy import DateTime, Date, Time

from utilities.list_and_dict import filter_dict_by_list


logger = logging.getLogger(__name__)


class DBObject():
    """Base class for implementing database objects."""

    db_views = []
    get_col_name = None
    time_col_name = None
    match_col_names = None

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # print(f'__init_subclass__ {cls.__name__}')
        if hasattr(cls, 'db'):
            cls.db.add_table(cls)

    @classmethod
    def setup(cls, db):
        # print(f'setup {cls.__name__}')
        if cls.time_col_name is None:
            cls.setup_table_vars()
        if hasattr(cls, 'create_view'):
            cls.create_view(db)

    @classmethod
    def setup_table_vars(cls):
        for col in cls.__table__._columns:
            if col.primary_key:
                logger.info("Found get_col_name %s for table %s", col.name, cls.__name__)
                cls.get_col_name = col.name
                if isinstance(col.type, DateTime) or isinstance(col.type, Date) or isinstance(col.type, Time):
                    logger.info("Found primary key time_col_name %s for table %s", col.name, cls.__name__)
                    cls.time_col_name = col.name
        if cls.time_col_name is None:
            for col in cls.__table__._columns:
                if isinstance(col.type, DateTime) or isinstance(col.type, Date) or isinstance(col.type, Time):
                    logger.info("Found time_col_name %s for table %s", col.name, cls.__name__)
                    cls.time_col_name = col.name
                    break
        if cls.time_col_name is not None:
            cls.time_col = synonym(cls.time_col_name)

    @classmethod
    def round_col_text(cls, col_name, alt_col_name=None, places=1, seperator=','):
        """Return a SQL phrase for rounding an optionally aliasing a column."""
        if alt_col_name is None:
            alt_col_name = col_name
        return literal_column(f'ROUND({col_name}, {places}) AS {alt_col_name}{seperator} ')

    @classmethod
    def round_col(cls, col_name, alt_col_name=None, places=1):
        """Return a SQL phrase for rounding an optionally aliasing a column."""
        return cls.round_col_text(col_name, alt_col_name, places, seperator='')

    @declared_attr
    def col_count(cls):
        """Return the number of columns in database object class."""
        if hasattr(cls, '__table__'):
            return len(cls.__table__.columns)

    @hybrid_method
    def during(self, start_ts, end_ts):
        """Return True if the databse object's timestamp is between the given times."""
        return self.time_col >= start_ts and self.time_col < end_ts

    @during.expression
    def during(cls, start_ts, end_ts):
        """Return True if the databse object's timestamp is between the given times."""
        return and_(cls.time_col >= start_ts, cls.time_col < end_ts)

    @hybrid_method
    def after(self, start_ts):
        """Return True if the databse object's timestamp is after the given time."""
        if start_ts is not None:
            return self.time_col >= start_ts

    @after.expression
    def after(cls, start_ts):
        """Return True if the databse object's timestamp is after the given time."""
        return cls.time_col >= start_ts

    @hybrid_method
    def before(self, end_ts):
        """Return True if the databse object's timestamp is before the given time."""
        return self.time_col < end_ts

    @before.expression
    def before(cls, end_ts):
        """Return True if the databse object's timestamp is before the given time."""
        return cls.time_col < end_ts

    @classmethod
    def _get_default_view_name(cls):
        return cls.__tablename__ + '_view'

    @classmethod
    def get_col_names(cls):
        """Return the column names of the database object."""
        return [col.name for col in cls.__table__.columns]

    @classmethod
    def get_col_by_name(cls, name):
        """Return the column object given the column name."""
        for col in cls.__table__._columns:
            if col.name == name:
                return col

    def update_from_dict(self, values_dict, ignore_none=False, ignore_zero=False):
        """Update a DB object instance from values in a dict by matching the dict keys to DB object attributes."""
        col_names = self.get_col_names()
        for key, value in values_dict.items():
            if (not ignore_none or value is not None) and (not ignore_zero or value != 0) and key in col_names:
                set_attribute(self, key, value)
        return self

    @classmethod
    def __delete_view(cls, db, view_name):
        """Delete a database view with name view_name."""
        with db.managed_session() as session:
            session.execute('DROP VIEW IF EXISTS ' + view_name)

    @classmethod
    def delete_view(cls, db, view_name=None):
        """Delete a database view with name view_name."""
        cls.__delete_view(db, view_name if view_name is not None else cls._get_default_view_name())

    @classmethod
    def __create_view_if_not_exists(cls, session, view_name, query_str):
        session.execute('CREATE VIEW IF NOT EXISTS ' + view_name + ' AS ' + query_str)

    @classmethod
    def create_view_if_doesnt_exist(cls, db, view_name, query_str):
        """Create a database view named view_name if ti doesn't already exist."""
        with db.managed_session() as session:
            cls.__create_view_if_not_exists(session, view_name, query_str)

    @classmethod
    def create_join_view(cls, db, view_name, selectable, join_table, filter_by=None, order_by=None):
        """Create a database view named view_name if ti doesn't already exist."""
        with db.managed_session() as session:
            query = Query(selectable, session=session).join(join_table)
            if filter_by is not None:
                query = query.filter(filter_by)
            if order_by is not None:
                query = query.order_by(order_by)
            cls.__create_view_if_not_exists(session, view_name, str(query))

    @classmethod
    def create_multi_join_view(cls, db, view_name, selectable, joins, order_by=None):
        """Create a database view named view_name if it doesn't already exist."""
        with db.managed_session() as session:
            query = Query(selectable, session=session)
            for (join_table, join_clause) in joins:
                query = query.join(join_table, join_clause)
            if order_by is not None:
                query = query.order_by(order_by)
            cls.__create_view_if_not_exists(session, view_name, str(query))

    @classmethod
    def create_view_from_selectable(cls, db, view_name, selectable, order_by):
        with db.managed_session() as session:
            query = Query(selectable, session=session).order_by(order_by)
            cls.__create_view_if_not_exists(session, view_name, str(query))

    @classmethod
    def intersection(cls, values_dict):
        """Return the dict elements whose keys are column names."""
        return filter_dict_by_list(values_dict, cls.get_col_names())

    @classmethod
    def s_get(cls, session, instance_id):
        """Return a single instance for the given id."""
        return session.query(cls).get(instance_id)

    @classmethod
    def get(cls, db, instance_id):
        """Return a single instance for the given id."""
        with db.managed_session() as session:
            return cls.s_get(session, instance_id)

    @classmethod
    def s_get_from_dict(cls, session, values_dict):
        """Return a single activity instance for the given id."""
        return cls.s_get(session, values_dict[cls.get_col_name])

    @classmethod
    def s_find_one(cls, session, values_dict):
        """Find a table row that matches the values in the values_dict."""
        query = session.query(cls)
        if cls.match_col_names is not None:
            for match_col_name in cls.match_col_names:
                if match_col_name in values_dict:
                    query = query.filter(cls.get_col_by_name(match_col_name) == values_dict[match_col_name])
                else:
                    query = query.filter(cls.get_col_by_name(match_col_name) == None)  # noqa
        else:
            query = query.filter(cls.time_col == values_dict[cls.time_col_name])
        query = query.filter(cls.time_col == values_dict[cls.time_col_name])
        return query.one_or_none()

    @classmethod
    def find_one(cls, db, values_dict):
        """Find a table row that matches the values in the values_dict."""
        with db.managed_session() as session:
            return cls.s_find_one(session, values_dict)

    @classmethod
    def s_find_match(cls, session, match_dict):
        """Find a table row that matches the values in the match_dict."""
        query = session.query(cls)
        for col, value in match_dict.items():
            query = query.filter(col == value)
        return query.one_or_none()

    @classmethod
    def s_find_id(cls, session, match_dict):
        """Return the id for a table row that matched the values in the match_dict."""
        return cls.s_find_match(session, match_dict).id

    @classmethod
    def find_id(cls, db, values_dict):
        """Return the id for a table row that matched the values in the values_dict."""
        with db.managed_session() as session:
            return cls.s_find_id(session, values_dict)

    @classmethod
    def s_find_or_create(cls, session, values_dict):
        if cls.s_find_one(session, values_dict) is None:
            session.add(cls(**values_dict))

    @classmethod
    def find_or_create(cls, db, values_dict):
        """Find a table row that matched the values in the values_dict. Create a row if not found."""
        with db.managed_session() as session:
            cls.s_find_or_create(session, values_dict)

    @classmethod
    def s_insert_or_update(cls, session, values_dict, ignore_none=True, ignore_zero=False):
        instance = cls.s_get_from_dict(session, values_dict)
        if instance:
            instance.update_from_dict(values_dict, ignore_none, ignore_zero)
        else:
            session.add(cls(**values_dict))

    @classmethod
    def insert_or_update(cls, db, values_dict, ignore_none=False):
        """Create a database record if it doesn't exist. Update it if does exist."""
        with db.managed_session() as session:
            cls.s_insert_or_update(session, values_dict, ignore_none)

    @classmethod
    def s_create_or_update(cls, session, values_dict, ignore_none=False, ignore_zero=False):
        instance = cls.s_find_one(session, values_dict)
        if instance:
            instance.update_from_dict(values_dict, ignore_none, ignore_zero)
        else:
            session.add(cls(**values_dict))

    @classmethod
    def create_or_update(cls, db, values_dict, ignore_none=False):
        """Create a database record if it doesn't exist. Update it if does exist."""
        with db.managed_session() as session:
            cls.s_create_or_update(session, values_dict, ignore_none)

    @classmethod
    def _secs_from_time(cls, col):
        return func.strftime('%s', col) - func.strftime('%s', '00:00')

    @classmethod
    def time_from_secs(cls, value):
        return func.time(value, 'unixepoch')

    @classmethod
    def row_to_int(cls, row):
        return int(row[0])

    @classmethod
    def row_to_int_not_none(cls, row):
        if row[0] is not None:
            return cls.row_to_int(row)

    @classmethod
    def rows_to_ints(cls, rows):
        return [cls.row_to_int(row) for row in rows]

    @classmethod
    def rows_to_ints_not_none(cls, rows):
        return [cls.row_to_int_not_none(row) for row in rows]

    @classmethod
    def row_to_month(cls, row):
        return datetime.date(1900, row, 1).strftime("%b")

    @classmethod
    def rows_to_months(cls, rows):
        return [cls.row_to_month(row) for row in rows]

    @classmethod
    def get_years(cls, db):
        with db.managed_session() as session:
            return cls.rows_to_ints_not_none(session.query(extract('year', cls.time_col)).distinct().all())

    @classmethod
    def _get_months(cls, session, year):
        return cls.rows_to_ints_not_none(session.query(extract('month', cls.time_col)).filter(extract('year', cls.time_col) == str(year)).distinct().all())

    @classmethod
    def get_months(cls, db, year):
        with db.managed_session() as session:
            return cls._get_months(session, year)

    @classmethod
    def get_month_names(cls, db, year):
        return cls.rows_to_months(cls.get_months(db, year))

    @classmethod
    def s_get_days(cls, session, year):
        return cls.rows_to_ints(session.query(func.strftime("%j", cls.time_col)).filter(extract('year', cls.time_col) == str(year)).distinct().all())

    @classmethod
    def get_days(cls, db, year):
        with db.managed_session() as session:
            return cls.s_get_days(session, year)

    @classmethod
    def s_query(cls, session, selectable, order_by=None, start_ts=None, end_ts=None, ignore_le_zero_col=None):
        query = session.query(selectable)
        if order_by is not None:
            query = query.order_by(order_by)
        if start_ts is not None and end_ts is not None:
            query = query.filter(cls.during(start_ts, end_ts))
        elif start_ts is not None:
            query = query.filter(cls.after(start_ts))
        elif end_ts is not None:
            query = query.filter(cls.before(end_ts))
        if ignore_le_zero_col is not None:
            query = query.filter(ignore_le_zero_col > 0)
        return query

    @classmethod
    def get_all(cls, db):
        """Return all DB records in the table."""
        with db.managed_session() as session:
            return session.query(cls).all()

    @classmethod
    def s_get_for_period(cls, session, start_ts, end_ts, selectable=None, not_none_col=None):
        """Return all DB records matching the selection criteria."""
        if selectable is None:
            selectable = cls
        query = cls.s_query(session, selectable, cls.time_col, start_ts, end_ts)
        if not_none_col is not None:
            # filter does not use 'is not None'
            query = query.filter(not_none_col != None)  # noqa
        return query.all()

    @classmethod
    def get_for_period(cls, db, start_ts, end_ts, selectable=None, not_none_col=None):
        """Return all DB records matching the selection criteria."""
        with db.managed_session() as session:
            return cls.s_get_for_period(session, start_ts, end_ts, selectable, not_none_col)

    @classmethod
    def _get_for_day(cls, db, day_date, selectable=None, not_none_col=None):
        """Return the values from a column for a given day."""
        start_ts = datetime.datetime.combine(day_date, datetime.time.min)
        end_ts = start_ts + datetime.timedelta(1)
        return cls.s_get_for_period(db, start_ts, end_ts, selectable, not_none_col)

    @classmethod
    def get_for_day(cls, db, selectable, day_date, not_none_col=None):
        """Return the values from a column for a given day."""
        start_ts = datetime.datetime.combine(day_date, datetime.time.min)
        end_ts = start_ts + datetime.timedelta(1)
        return cls.get_for_period(db, start_ts, end_ts, selectable, not_none_col)

    @classmethod
    def get_col_values(cls, db, get_col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the values from a column possibly filtered by time period."""
        with db.managed_session() as session:
            return cls.s_query(session, get_col, cls.time_col, start_ts, end_ts, ignore_le_zero).filter(match_col == match_value).all()

    @classmethod
    def s_get_col_func_query(cls, session, col, func, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.s_query(session, func(col), None, start_ts, end_ts, col if ignore_le_zero else None)

    @classmethod
    def get_col_distinct(cls, db, col, start_ts=None, end_ts=None):
        """Return the set of distinct value from a column possibly filtered by time period."""
        with db.managed_session() as session:
            return [row[0] for row in cls.s_get_col_func_query(session, col, func.distinct, start_ts, end_ts).all()]

    @classmethod
    def s_get_col_avg(cls, session, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the average value of a column filtered by criteria."""
        return cls.s_get_col_func_query(session, col, func.avg, start_ts, end_ts, col if ignore_le_zero else None).scalar()

    @classmethod
    def get_col_avg(cls, db, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the average value of a column filtered by criteria."""
        with db.managed_session() as session:
            return cls.s_get_col_avg(session, col, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def s_get_col_min(cls, session, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the minimum value in a column filtered by criteria."""
        return cls.s_get_col_func_query(session, col, func.min, start_ts, end_ts, col if ignore_le_zero else None).scalar()

    @classmethod
    def get_col_min(cls, db, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the minimum value in a column filtered by criteria."""
        with db.managed_session() as session:
            return cls.s_get_col_func_query(session, col, func.min, start_ts, end_ts, col if ignore_le_zero else None).scalar()

    @classmethod
    def s_get_col_max(cls, session, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the maximum value in a column filtered by criteria."""
        return cls.s_get_col_func_query(session, col, func.max, start_ts, end_ts, ignore_le_zero).scalar()

    @classmethod
    def get_col_max(cls, db, col, start_ts=None, end_ts=None, ignore_le_zero=False):
        """Return the maximum value in a column filtered by criteria."""
        with db.managed_session() as session:
            return cls.s_get_col_func_query(session, col, func.max, start_ts, end_ts, ignore_le_zero).scalar()

    @classmethod
    def s_get_col_sum(cls, session, col, start_ts=None, end_ts=None):
        """Return the sum of a column filtered by criteria."""
        return cls.s_get_col_func_query(session, col, func.sum, start_ts, end_ts).scalar()

    @classmethod
    def get_col_sum(cls, db, col, start_ts=None, end_ts=None):
        """Return the sum of a column filtered by criteria."""
        with db.managed_session() as session:
            return cls.s_get_col_sum(session, col, start_ts, end_ts)

    @classmethod
    def __get_time_col_func(cls, session, col, stat_func, start_ts=None, end_ts=None):
        result = (
            cls.s_query(session, cls.time_from_secs(stat_func(cls._secs_from_time(col))),
                        None, start_ts, end_ts, cls._secs_from_time(col)).scalar()
        )
        return datetime.datetime.strptime(result, '%H:%M:%S').time() if result is not None else datetime.time.min

    @classmethod
    def get_time_col_func(cls, db, col, stat_func, start_ts=None, end_ts=None):
        with db.managed_session() as session:
            return cls.__get_time_col_func(session, col, stat_func, start_ts, end_ts)

    @classmethod
    def s_get_time_col_avg(cls, session, col, start_ts=None, end_ts=None):
        return cls.__get_time_col_func(session, col, func.avg, start_ts, end_ts)

    @classmethod
    def get_time_col_avg(cls, db, col, start_ts=None, end_ts=None):
        return cls.get_time_col_func(db, col, func.avg, start_ts, end_ts)

    @classmethod
    def s_get_time_col_min(cls, session, col, start_ts=None, end_ts=None):
        return cls.__get_time_col_func(session, col, func.min, start_ts, end_ts)

    @classmethod
    def get_time_col_min(cls, db, col, start_ts=None, end_ts=None):
        return cls.get_time_col_func(db, col, func.min, start_ts, end_ts)

    @classmethod
    def s_get_time_col_max(cls, session, col, start_ts=None, end_ts=None):
        return cls.__get_time_col_func(session, col, func.max, start_ts, end_ts)

    @classmethod
    def get_time_col_max(cls, db, col, start_ts=None, end_ts=None):
        return cls.get_time_col_func(db, col, func.max, start_ts, end_ts)

    @classmethod
    def s_get_time_col_sum(cls, session, col, start_ts=None, end_ts=None):
        return cls.__get_time_col_func(session, col, func.sum, start_ts, end_ts)

    @classmethod
    def get_time_col_sum(cls, db, col, start_ts=None, end_ts=None):
        return cls.get_time_col_func(db, col, func.sum, start_ts, end_ts)

    @classmethod
    def get_col_latest(cls, db, col, ignore_le_zero=False):
        """Return the most recent value for the given column."""
        with db.managed_session() as session:
            query = session.query(col)
            if ignore_le_zero:
                if col == cls.time_col:
                    query = query.filter(cls._secs_from_time(col) > 0)
                else:
                    query = query.filter(col > 0)
            return query.order_by(desc(cls.time_col)).limit(1).scalar()

    @classmethod
    def get_time_col_latest(cls, db, col):
        with db.managed_session() as session:
            return session.query(col).filter(cls._secs_from_time(col) > 0).order_by(desc(cls.time_col)).limit(1).scalar()

    @classmethod
    def s_get_col_func_of_max_per_day_for_value(cls, session, col, stat_func, start_ts, end_ts, match_col=None, match_value=None):
        max_daily_query = (
            session.query(func.max(col).label('maxes')).filter(cls.during(start_ts, end_ts)).group_by(func.strftime("%j", cls.time_col))
        )
        if match_col is not None and match_value is not None:
            max_daily_query.filter(match_col == match_value)
        return session.query(stat_func(max_daily_query.subquery().columns.maxes)).scalar()

    @classmethod
    def get_col_func_of_max_per_day_for_value(cls, db, col, stat_func, start_ts, end_ts, match_col=None, match_value=None):
        with db.managed_session() as session:
            return cls.s_get_col_func_of_max_per_day_for_value(session, col, stat_func, start_ts, end_ts, match_col, match_value)

    @classmethod
    def get_col_sum_of_max_per_day_for_value(cls, db, col, match_col, match_value, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day_for_value(db, col, func.sum, start_ts, end_ts, match_col, match_value)

    @classmethod
    def s_get_col_avg_of_max_per_day_for_value(cls, session, col, match_col, match_value, start_ts, end_ts):
        return cls.s_get_col_func_of_max_per_day_for_value(session, col, func.avg, start_ts, end_ts, match_col, match_value)

    @classmethod
    def get_col_avg_of_max_per_day_for_value(cls, db, col, match_col, match_value, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day_for_value(db, col, func.avg, start_ts, end_ts, match_col, match_value)

    @classmethod
    def s_get_col_func_of_max_per_day(cls, session, col, stat_func, start_ts, end_ts):
        return cls.s_get_col_func_of_max_per_day_for_value(session, col, func.sum, start_ts, end_ts)

    @classmethod
    def get_col_func_of_max_per_day(cls, db, col, stat_func, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day_for_value(db, col, func.sum, start_ts, end_ts)

    @classmethod
    def s_get_col_sum_of_max_per_day(cls, session, col, start_ts, end_ts):
        return cls.s_get_col_func_of_max_per_day(session, col, func.sum, start_ts, end_ts)

    @classmethod
    def get_col_sum_of_max_per_day(cls, db, col, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day(db, col, func.sum, start_ts, end_ts)

    @classmethod
    def get_col_avg_of_max_per_day(cls, db, col, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day(db, col, func.avg, start_ts, end_ts)

    @classmethod
    def get_col_min_of_max_per_day(cls, db, col, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day(db, col, func.min, start_ts, end_ts)

    @classmethod
    def get_col_max_of_max_per_day(cls, db, col, start_ts, end_ts):
        return cls.get_col_func_of_max_per_day(db, col, func.max, start_ts, end_ts)

    @classmethod
    def latest_time(cls, db, not_zero_col):
        return cls.get_col_max_greater_than_value(db, cls.time_col, not_zero_col, 0)

    @classmethod
    def row_count(cls, db, col=None, col_value=None):
        with db.managed_session() as session:
            query = session.query(cls)
            if col is not None:
                query = query.filter(col == col_value)
            return query.count()

    @classmethod
    def s_row_count_for_period(cls, session, start_ts, end_ts):
        return session.query(cls).filter(cls.time_col >= start_ts).filter(cls.time_col < end_ts).count()

    @classmethod
    def row_count_for_period(cls, db, start_ts, end_ts):
        with db.managed_session() as session:
            return cls.s_row_count_for_period(session, start_ts, end_ts)

    @classmethod
    def s_row_count_for_day(cls, session, day_date):
        start_ts = datetime.datetime.combine(day_date, datetime.time.min)
        end_ts = start_ts + datetime.timedelta(days=1)
        return cls.s_row_count_for_period(session, start_ts, end_ts)

    @classmethod
    def row_count_for_day(cls, db, day_date):
        start_ts = datetime.datetime.combine(day_date, datetime.time.min)
        end_ts = start_ts + datetime.timedelta(days=1)
        return cls.row_count_for_period(db, start_ts, end_ts)

    @classmethod
    def _get_col_func_for_value(cls, session, col, stat_func, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.s_query(session, stat_func(col), None, start_ts, end_ts, col if ignore_le_zero else None).filter(match_col == match_value).scalar()

    @classmethod
    def get_col_func_for_value(cls, db, col, stat_func, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        with db.managed_session() as session:
            return cls.s_query(session, stat_func(col), None, start_ts, end_ts, col if ignore_le_zero else None).filter(match_col == match_value).scalar()

    @classmethod
    def _get_col_sum_for_value(cls, session, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls._get_col_func_for_value(session, col, func.sum, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_sum_for_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_for_value(db, col, func.sum, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def s_get_col_avg_for_value(cls, session, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls._get_col_func_for_value(session, col, func.avg, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_avg_for_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_for_value(db, col, func.avg, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def s_get_col_min_for_value(cls, session, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls._get_col_func_for_value(session, col, func.min, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_min_for_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_for_value(db, col, func.min, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def s_get_col_max_for_value(cls, session, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls._get_col_func_for_value(session, col, func.max, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_max_for_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_for_value(db, col, func.max, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_func_greater_than_value(cls, db, col, stat_func, match_col, match_value, start_ts=None, end_ts=None):
        with db.managed_session() as session:
            return cls.s_query(session, stat_func(col), None, start_ts, end_ts).filter(match_col > match_value).scalar()

    @classmethod
    def get_col_avg_greater_than_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None):
        return cls.get_col_func_greater_than_value(db, col, func.avg, match_col, match_value, start_ts, end_ts)

    @classmethod
    def get_col_max_greater_than_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None):
        return cls.get_col_func_greater_than_value(db, col, func.max, match_col, match_value, start_ts, end_ts)

    @classmethod
    def get_col_func_less_than_value(cls, db, col, stat_func, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        with db.managed_session() as session:
            return cls.s_query(session, stat_func(col), None, start_ts, end_ts, col if ignore_le_zero else None).filter(match_col < match_value).scalar()

    @classmethod
    def get_col_avg_less_than_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_less_than_value(db, col, func.avg, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_min_less_than_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_less_than_value(db, col, func.min, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_col_max_less_than_value(cls, db, col, match_col, match_value, start_ts=None, end_ts=None, ignore_le_zero=False):
        return cls.get_col_func_less_than_value(db, col, func.max, match_col, match_value, start_ts, end_ts, ignore_le_zero)

    @classmethod
    def get_daily_stats(cls, session, day_ts):
        """Return a dictionary of aggregate statistics for the given day."""
        stats = cls.get_stats(session, day_ts, day_ts + datetime.timedelta(1))
        stats['day'] = day_ts
        return stats

    @classmethod
    def get_weekly_stats(cls, session, first_day_ts):
        """Return a dictionary of aggregate statistics for the given week."""
        stats = cls.get_stats(session, first_day_ts, first_day_ts + datetime.timedelta(7))
        stats['first_day'] = first_day_ts
        return stats

    @classmethod
    def get_monthly_stats(cls, session, first_day_ts, last_day_ts):
        """Return a dictionary of aggregate statistics for the given month."""
        stats = cls.get_stats(session, first_day_ts, last_day_ts)
        stats['first_day'] = first_day_ts
        return stats

    @classmethod
    def get_yearly_stats(cls, session, year):
        """Return a dictionary of aggregate statistics for the given year."""
        first_day_ts = datetime.datetime(year, 1, 1)
        return cls.get_monthly_stats(session, first_day_ts, first_day_ts + datetime.timedelta(365))

    def __repr__(self):
        """Return a string representation of a DBObject instance."""
        classname = self.__class__.__name__
        values = {col_name : getattr(self, col_name) for col_name in self.get_col_names()}
        return ("<%s() %r>" % (classname, values))