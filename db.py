"""Transactional DarkMoney storage, compatible with the original users table."""
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Column, Integer, String, LargeBinary, create_engine, select, func, or_, and_
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy.types import TypeDecorator

from cogs.mission_rules import MISSIONS

Base = declarative_base()
MAX_BALANCE = 9_000_000_000_000_000
DAILY_TIMEZONE = timezone(timedelta(hours=-3))


def next_daily_reset(timestamp):
    """Next midnight at fixed GMT-3, independent of the host's timezone."""
    local = datetime.fromtimestamp(timestamp, DAILY_TIMEZONE)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight + timedelta(days=1)).timestamp())


class CoinInteger(TypeDecorator):
    """Keep legacy SQLite integers; encode larger winnings without float rounding.

    SQLite sorts blobs above integers. A length prefix keeps positive overflow
    values sorted numerically too, so the existing rich-list queries still work.
    """
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or -(2 ** 63) <= value < 2 ** 63:
            return value
        digits = str(value).encode("ascii")
        return len(digits).to_bytes(4, "big") + digits

    def process_result_value(self, value, dialect):
        if isinstance(value, bytes):
            return int(value[4:])
        return value


class EconomyError(ValueError):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True)
    balance = Column(CoinInteger, default=0)


class Bet(Base):
    __tablename__ = "bets"
    id = Column(String, primary_key=True)
    discord_id = Column(String, nullable=False, index=True)
    game = Column(String, nullable=False)
    stake = Column(CoinInteger, nullable=False)
    status = Column(String, nullable=False, default="active")
    payout = Column(CoinInteger, default=0)


class DailyClaim(Base):
    __tablename__ = "daily_claims"
    discord_id = Column(String, primary_key=True)
    claimed_at = Column(Integer, nullable=False)


class MissionProgress(Base):
    __tablename__ = "mission_progress"
    discord_id = Column(String, primary_key=True)
    mission = Column(String, primary_key=True)
    day_start = Column(Integer, nullable=False)
    progress = Column(Integer, nullable=False, default=0)
    claimed = Column(Integer, nullable=False, default=0)


class SocialProfile(Base):
    __tablename__ = "social_profiles"
    discord_id = Column(String, primary_key=True)
    color = Column(String(7), nullable=False, default="#101C24")
    about = Column(String(300), nullable=False, default="")
    background = Column(LargeBinary, nullable=True)


class ShipScore(Base):
    __tablename__ = "ship_scores"
    first_id = Column(String, primary_key=True)
    second_id = Column(String, primary_key=True)
    percentage = Column(Integer, nullable=False)


class Marriage(Base):
    __tablename__ = "marriages"
    id = Column(String, primary_key=True)
    first_id = Column(String, nullable=False, unique=True)
    second_id = Column(String, nullable=False, unique=True)
    married_at = Column(Integer, nullable=False)


class MarriageAffinity(Base):
    __tablename__ = "marriage_affinity"
    marriage_id = Column(String, primary_key=True)
    points = Column(Integer, nullable=False, default=0)


class TicketConfig(Base):
    __tablename__ = "ticket_configs"
    guild_id = Column(String, primary_key=True)
    category_id = Column(String, nullable=False)
    next_number = Column(Integer, nullable=False, default=1)


class Database:
    def __init__(self, url):
        self.engine = create_engine(url, connect_args={"timeout": 10})
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with Session(self.engine) as session:
            # Serialize read/check/write operations across SQLite connections.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @staticmethod
    def user(session, discord_id):
        user = session.scalar(select(User).where(User.discord_id == str(discord_id)))
        if user is None:
            user = User(discord_id=str(discord_id), balance=0)
            session.add(user)
            session.flush()
        return user

    @staticmethod
    def positive(amount, maximum=MAX_BALANCE):
        if type(amount) is not int or not 1 <= amount <= maximum:
            raise EconomyError(f"Use um valor inteiro entre 1 e {maximum:,} D$.")

    @staticmethod
    def credit(user, amount):
        if user.balance + amount > MAX_BALANCE:
            raise EconomyError("O saldo de destino excederia o limite de D$.")
        user.balance += amount

    def balance(self, discord_id):
        with self.transaction() as session:
            return self.user(session, discord_id).balance

    def add_balance(self, discord_id, amount):
        self.positive(amount)
        with self.transaction() as session:
            user = self.user(session, discord_id)
            self.credit(user, amount)
            return user.balance

    def set_balance(self, discord_id, amount):
        if type(amount) is not int or not 0 <= amount <= MAX_BALANCE:
            raise EconomyError(f"Use um saldo inteiro entre 0 e {MAX_BALANCE:,} D$.")
        with self.transaction() as session:
            user = self.user(session, discord_id)
            user.balance = amount
            return user.balance

    def reset_balance(self, discord_id):
        return self.set_balance(discord_id, 0)

    def transfer(self, sender_id, receiver_id, amount):
        self.positive(amount)
        with self.transaction() as session:
            sender = self.user(session, sender_id)
            if sender.balance < amount:
                raise EconomyError("Você não tem saldo suficiente.")
            if str(sender_id) != str(receiver_id):
                receiver = self.user(session, receiver_id)
                self.credit(receiver, amount)
                sender.balance -= amount
            return sender.balance

    @staticmethod
    def advance_mission(session, discord_id, key, now):
        definition = next(mission for mission in MISSIONS if mission.key == key)
        day_start = next_daily_reset(now) - 86400
        row = session.get(MissionProgress, (str(discord_id), key))
        if row is None:
            session.add(MissionProgress(discord_id=str(discord_id), mission=key,
                                        day_start=day_start, progress=1, claimed=0))
        else:
            if row.day_start != day_start:
                row.day_start, row.progress, row.claimed = day_start, 0, 0
            row.progress = min(definition.target, row.progress + 1)

    def mission_status(self, discord_id, now=None):
        now = int(time.time() if now is None else now)
        reset_at = next_daily_reset(now)
        with Session(self.engine) as session:
            rows = {row.mission: row for row in session.scalars(
                select(MissionProgress).where(
                    MissionProgress.discord_id == str(discord_id),
                    MissionProgress.day_start == reset_at - 86400))}
            return [{"mission": mission,
                     "progress": rows[mission.key].progress if mission.key in rows else 0,
                     "claimed": bool(rows[mission.key].claimed) if mission.key in rows else False}
                    for mission in MISSIONS], reset_at

    def claim_missions(self, discord_id, now=None):
        """Credit all completed daily missions atomically, at most once each."""
        with self.transaction() as session:
            now = int(time.time() if now is None else now)
            day_start = next_daily_reset(now) - 86400
            completed = []
            for mission in MISSIONS:
                row = session.get(MissionProgress, (str(discord_id), mission.key))
                if (row is not None and row.day_start == day_start
                        and row.progress >= mission.target and not row.claimed):
                    completed.append((mission, row))
            if not completed:
                raise EconomyError("Nenhuma recompensa disponível. Veja seu progresso com r.missions ou /missions.")
            reward = sum(mission.reward for mission, _ in completed)
            user = self.user(session, discord_id)
            self.credit(user, reward)
            for _, row in completed:
                row.claimed = 1
            return reward, user.balance

    def job_reward(self, discord_id, job, reward, now=None):
        """Persist job income and mission progress in the same transaction."""
        if job not in {"work", "freelance"}:
            raise EconomyError("Trabalho inválido.")
        self.positive(reward)
        with self.transaction() as session:
            now = int(time.time() if now is None else now)
            user = self.user(session, discord_id)
            self.credit(user, reward)
            self.advance_mission(session, discord_id, job, now)
            return user.balance

    def daily(self, discord_id, reward, now=None):
        self.positive(reward)
        with self.transaction() as session:
            now = int(time.time() if now is None else now)
            day_start = next_daily_reset(now) - 86400
            claim = session.get(DailyClaim, str(discord_id))
            if claim and claim.claimed_at >= day_start:
                reset_at = next_daily_reset(claim.claimed_at)
                raise EconomyError("Você já recebeu sua recompensa diária de hoje. "
                                   f"Disponível novamente <t:{reset_at}:R> (00:00 GMT-3).")
            user = self.user(session, discord_id)
            self.credit(user, reward)
            if claim:
                claim.claimed_at = now
            else:
                session.add(DailyClaim(discord_id=str(discord_id), claimed_at=now))
            self.advance_mission(session, discord_id, "daily", now)
            return user.balance

    def reserve_bet(self, discord_id, game, stake):
        with self.transaction() as session:
            active = session.scalar(select(Bet.id).where(
                Bet.discord_id == str(discord_id), Bet.status == "active"))
            if active:
                raise EconomyError("Você já tem um jogo em andamento. Termine-o primeiro.")
            user = self.user(session, discord_id)
            # Resolve balance aliases in the same transaction as the debit.
            if stake == "all":
                stake = user.balance
            elif stake == "half":
                stake = user.balance // 2
            if type(stake) is not int or stake <= 0:
                raise EconomyError("A aposta deve ser de pelo menos 1 D$. Half usa metade do saldo, arredondada para baixo.")
            if user.balance < stake:
                raise EconomyError("Você não tem saldo suficiente para essa aposta.")
            user.balance -= stake
            bet_id = uuid.uuid4().hex
            session.add(Bet(id=bet_id, discord_id=str(discord_id), game=game, stake=stake))
            return bet_id

    def bet_stake(self, bet_id):
        with Session(self.engine) as session:
            bet = session.get(Bet, bet_id)
            if bet is None:
                raise EconomyError("Aposta não encontrada.")
            return bet.stake

    def settle_bet(self, bet_id, payout=None):
        """Settle once. None refunds the stake; repeated calls cannot pay twice."""
        if payout is not None and (type(payout) is not int or payout < 0):
            raise EconomyError("Pagamento inválido.")
        with self.transaction() as session:
            bet = session.get(Bet, bet_id)
            if bet is None:
                raise EconomyError("Aposta não encontrada.")
            user = self.user(session, bet.discord_id)
            if bet.status != "active":
                return user.balance
            amount = bet.stake if payout is None else payout
            # Preserve full winnings, including amounts above SQLite's integer range.
            user.balance += amount
            bet.payout = amount
            bet.status = "refunded" if payout is None else "settled"
            return user.balance

    def recover_bets(self):
        """Refund unfinished games once on startup, before accepting commands."""
        with self.transaction() as session:
            bets = session.scalars(select(Bet).where(Bet.status == "active")).all()
            for bet in bets:
                self.user(session, bet.discord_id).balance += bet.stake
                bet.payout, bet.status = bet.stake, "refunded"
            return len(bets)

    def leaderboard(self, page=1, page_size=10):
        with Session(self.engine) as session:
            total = session.scalar(select(func.count()).select_from(User))
            rows = session.execute(select(User.discord_id, User.balance).order_by(
                User.balance.desc(), User.discord_id.asc()).offset(
                    (page - 1) * page_size).limit(page_size)).all()
            return [(row.discord_id, row.balance) for row in rows], total

    @staticmethod
    def social_profile(session, discord_id):
        profile = session.get(SocialProfile, str(discord_id))
        if profile is None:
            profile = SocialProfile(discord_id=str(discord_id))
            session.add(profile)
            session.flush()
        return profile

    def profile(self, discord_id):
        with self.transaction() as session:
            user = self.user(session, discord_id)
            profile = self.social_profile(session, discord_id)
            ahead = session.scalar(select(func.count()).select_from(User).where(or_(
                User.balance > user.balance,
                and_(User.balance == user.balance, User.discord_id < user.discord_id),
            )))
            return {"discord_id": user.discord_id, "balance": user.balance, "rank": ahead + 1,
                    "color": profile.color, "about": profile.about, "background": profile.background}

    def update_profile(self, discord_id, **changes):
        if not changes or changes.keys() - {"color", "about", "background"}:
            raise EconomyError("Campo de perfil inválido.")
        with self.transaction() as session:
            self.user(session, discord_id)
            profile = self.social_profile(session, discord_id)
            for field, value in changes.items():
                setattr(profile, field, value)

    @staticmethod
    def pair(first_id, second_id):
        pair = tuple(sorted((str(first_id), str(second_id))))
        if pair[0] == pair[1]:
            raise EconomyError("Escolha duas pessoas diferentes.")
        return pair

    def ship_score(self, first_id, second_id):
        first_id, second_id = self.pair(first_id, second_id)
        with self.transaction() as session:
            score = session.get(ShipScore, (first_id, second_id))
            if score is None:
                score = ShipScore(first_id=first_id, second_id=second_id, percentage=secrets.randbelow(101))
                session.add(score)
            return score.percentage

    def marry(self, first_id, second_id, now=None):
        """Called only after both participants confirm; serialize spouse checks."""
        first_id, second_id = self.pair(first_id, second_id)
        with self.transaction() as session:
            existing = session.scalar(select(Marriage.id).where(or_(
                Marriage.first_id.in_((first_id, second_id)),
                Marriage.second_id.in_((first_id, second_id)),
            )))
            if existing is not None:
                raise EconomyError("Uma das pessoas já está casada. O pedido não pode ser concluído.")
            married_at = int(time.time() if now is None else now)
            session.add(Marriage(id=uuid.uuid4().hex, first_id=first_id,
                                 second_id=second_id, married_at=married_at))
            return {"first_id": first_id, "second_id": second_id, "married_at": married_at, "affinity": 0}

    def marriage(self, discord_id):
        with Session(self.engine) as session:
            marriage = session.scalar(select(Marriage).where(or_(
                Marriage.first_id == str(discord_id), Marriage.second_id == str(discord_id))))
            if marriage is None:
                return None
            affinity = session.get(MarriageAffinity, marriage.id)
            return {"first_id": marriage.first_id, "second_id": marriage.second_id,
                    "married_at": marriage.married_at, "affinity": affinity.points if affinity else 0}

    def add_marriage_affinity(self, first_id, second_id, points):
        """Award points atomically only when these two people are married."""
        if type(points) is not int or not 1 <= points <= 3:
            raise EconomyError("A afinidade deve aumentar entre 1 e 3 pontos.")
        first_id, second_id = self.pair(first_id, second_id)
        with self.transaction() as session:
            marriage = session.scalar(select(Marriage).where(
                Marriage.first_id == first_id, Marriage.second_id == second_id))
            if marriage is None:
                return 0
            affinity = session.get(MarriageAffinity, marriage.id)
            if affinity is None:
                session.add(MarriageAffinity(marriage_id=marriage.id, points=points))
            else:
                affinity.points += points
            return points

    def configure_tickets(self, guild_id, category_id):
        with self.transaction() as session:
            config = session.get(TicketConfig, str(guild_id))
            if config is None:
                config = TicketConfig(guild_id=str(guild_id), category_id=str(category_id), next_number=1)
                session.add(config)
            else:
                config.category_id = str(category_id)

    def ticket_category(self, guild_id):
        with Session(self.engine) as session:
            config = session.get(TicketConfig, str(guild_id))
            return int(config.category_id) if config is not None else None

    def next_ticket_number(self, guild_id):
        """Reserve a server-local ticket number atomically."""
        with self.transaction() as session:
            config = session.get(TicketConfig, str(guild_id))
            if config is None:
                raise EconomyError("O painel de tickets ainda não foi configurado.")
            number = config.next_number
            config.next_number += 1
            return number


database = Database(os.getenv("BOT_DATABASE_URL", "sqlite:///" +
                             (Path(__file__).parent / "bot.db").as_posix()))
