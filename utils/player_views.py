import csv
import io


def history_csv(database, user_id):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Дата", "Тип", "Сумма TON", "Описание"])
    for row in database.get_transactions(user_id, limit=1000):
        description = row.get("description") or ""
        if description.lstrip().startswith(("=", "+", "-", "@")):
            description = "'" + description
        writer.writerow([row["created_at"], row["type"], row["amount"], description])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
