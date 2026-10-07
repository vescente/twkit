from twkit import dryrun


def _tr(dialect: str = 'hyper') -> dryrun.Translator:
    return dryrun.Translator({}, {}, {}, {'date', 'value', 'dim_1', 'measure'}, dialect=dialect)


def test_nested_dateadd_arguments_translated():
    tr = _tr()
    formula = ("SUM(IF [date] >= DATEADD('day', -(DATEDIFF('day', "
               "[Parameters].[p_start_dt], [Parameters].[p_end_dt]) + 1), "
               "[Parameters].[p_start_dt]) THEN [value] END)")
    sql, why = tr.to_sql(formula)

    assert not why, why
    assert 'DATEADD' not in sql.upper()
    assert 'DATEDIFF' not in sql.upper()
    assert 'INTERVAL' in sql.upper(), sql


def test_typed_literal_not_concat():
    tr = _tr()
    sql, why = tr.to_sql("DATEADD('day', 7, #2026-01-01#)")

    assert not why, why
    assert '||' not in sql


def test_string_concat_still_translated():
    tr = _tr()
    sql, why = tr.to_sql("'W ' + STR([dim_1])")

    assert not why, why
    assert '||' in sql
