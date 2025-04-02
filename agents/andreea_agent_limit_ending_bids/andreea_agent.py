import logging
from random import randint
import random
import sys
from time import time
from typing import cast
import json

from geniusweb.actions.Accept import Accept
from geniusweb.actions.Action import Action
from geniusweb.actions.Offer import Offer
from geniusweb.actions.PartyId import PartyId
from geniusweb.bidspace.AllBidsList import AllBidsList
from geniusweb.inform.ActionDone import ActionDone
from geniusweb.inform.Finished import Finished
from geniusweb.inform.Inform import Inform
from geniusweb.inform.Settings import Settings
from geniusweb.inform.YourTurn import YourTurn
from geniusweb.issuevalue.Bid import Bid
from geniusweb.issuevalue.Domain import Domain
from geniusweb.party.Capabilities import Capabilities
from geniusweb.party.DefaultParty import DefaultParty
from geniusweb.profile.utilityspace.LinearAdditiveUtilitySpace import (
    LinearAdditiveUtilitySpace,
)
from geniusweb.profileconnection.ProfileConnectionFactory import (
    ProfileConnectionFactory,
)
from geniusweb.progress.ProgressTime import ProgressTime
from geniusweb.references.Parameters import Parameters
from tudelft_utilities_logging.ReportToLogger import ReportToLogger

from .utils.opponent_model import OpponentModel


class VeryCoolAgentV4(DefaultParty):
    """
    Template of a Python geniusweb agent.
    """

    def __init__(self):
        super().__init__()
        self.logger: ReportToLogger = self.getReporter()

        self.domain: Domain = None
        self.parameters: Parameters = None
        self.profile: LinearAdditiveUtilitySpace = None
        self.progress: ProgressTime = None
        self.me: PartyId = None
        self.other: str = None
        self.settings: Settings = None
        self.storage_dir: str = None

        self.last_received_bid: Bid = None
        self.opponent_model: OpponentModel = None

        self.strategy = "boulware"
        self.opponent_concessions = []
        self.historical_concessions = self.load_data()

        self.sent_bids: list[Bid] = []

        self.logger.log(logging.INFO, "party is initialized")

    def notifyChange(self, data: Inform):
        """MUST BE IMPLEMENTED
        This is the entry point of all interaction with your agent after is has been initialised.
        How to handle the received data is based on its class type.

        Args:
            info (Inform): Contains either a request for action or information.
        """

        # a Settings message is the first message that will be send to your
        # agent containing all the information about the negotiation session.
        if isinstance(data, Settings):
            self.settings = cast(Settings, data)
            self.me = self.settings.getID()

            # progress towards the deadline has to be tracked manually through the use of the Progress object
            self.progress = self.settings.getProgress()

            self.parameters = self.settings.getParameters()
            self.storage_dir = self.parameters.get("storage_dir")

            # the profile contains the preferences of the agent over the domain
            profile_connection = ProfileConnectionFactory.create(
                data.getProfile().getURI(), self.getReporter()
            )
            self.profile = profile_connection.getProfile()
            self.domain = self.profile.getDomain()
            profile_connection.close()

        # ActionDone informs you of an action (an offer or an accept)
        # that is performed by one of the agents (including yourself).
        elif isinstance(data, ActionDone):
            action = cast(ActionDone, data).getAction()
            actor = action.getActor()

            # ignore action if it is our action
            if actor != self.me:
                # obtain the name of the opponent, cutting of the position ID.
                self.other = str(actor).rsplit("_", 1)[0]

                # process action done by opponent
                self.opponent_action(action)
        # YourTurn notifies you that it is your turn to act
        elif isinstance(data, YourTurn):
            # execute a turn
            self.my_turn()

        # Finished will be send if the negotiation has ended (through agreement or deadline)
        elif isinstance(data, Finished):
            self.save_data()
            # terminate the agent MUST BE CALLED
            self.logger.log(logging.INFO, "party is terminating:")
            super().terminate()
        else:
            self.logger.log(logging.WARNING, "Ignoring unknown info " + str(data))

    def getCapabilities(self) -> Capabilities:
        """MUST BE IMPLEMENTED
        Method to indicate to the protocol what the capabilities of this agent are.
        Leave it as is for the ANL 2022 competition

        Returns:
            Capabilities: Capabilities representation class
        """
        return Capabilities(
            set(["SAOP"]),
            set(["geniusweb.profile.utilityspace.LinearAdditive"]),
        )

    def send_action(self, action: Action):
        """Sends an action to the opponent(s)

        Args:
            action (Action): action of this agent
        """
        self.getConnection().send(action)

    # give a description of your agent
    def getDescription(self) -> str:
        """MUST BE IMPLEMENTED
        Returns a description of your agent. 1 or 2 sentences.

        Returns:
            str: Agent description
        """
        return "VeryCoolAgent dynamically switches negotiation strategy based on opponent behavior and progress."

    def opponent_action(self, action):
        """Process an action that was received from the opponent.

        Args:
            action (Action): action of opponent
        """
        # if it is an offer, set the last received bid
        if isinstance(action, Offer):
            # create opponent model if it was not yet initialised
            if self.opponent_model is None:
                self.opponent_model = OpponentModel(self.domain)

            bid = cast(Offer, action).getBid()

            # update opponent model with bid
            self.opponent_model.update(bid)
            # set bid as last received
            self.last_received_bid = bid
            self.track_concessions(bid)  # Track opponent's concession behavior
            self.adjust_strategy()  # Adjust negotiation strategy based on progress

    def track_concessions(self, bid: Bid):
        utility = self.profile.getUtility(bid)
        if self.opponent_concessions and utility < self.opponent_concessions[-1]:
            self.opponent_concessions.append(utility)
        elif not self.opponent_concessions:
            self.opponent_concessions.append(utility)

    def adjust_strategy(self):
        progress = self.progress.get(time() * 1000)
        if progress < 0.3:
            self.strategy = "boulware"
        elif progress < 0.7:
            self.strategy = "linear"
        else:
            self.strategy = "conceder"

    def my_turn(self):
        """This method is called when it is our turn. It should decide upon an action
        to perform and send this action to the opponent.
        """
        # check if the last received offer is good enough
        if self.accept_condition(self.last_received_bid):
            # if so, accept the offer
            action = Accept(self.me, self.last_received_bid)
        else:
            # if not, find a bid to propose as counter offer
            bid = self.find_bid()
            self.sent_bids.append(bid)
            action = Offer(self.me, bid)

        # send the action
        self.send_action(action)

    def save_data(self):
        data = {"historical_concessions": [float(c) for c in self.opponent_concessions]}
        with open("data.json", "w") as f:
            json.dump(data, f)

    def load_data(self):
        try:
            with open("data.json", "r") as f:
                data = json.load(f)
                return data.get("historical_concessions", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    ###########################################################################################
    ################################## Example methods below ##################################
    ###########################################################################################

    def accept_condition(self, bid: Bid) -> bool:
        if bid is None:
            return False

        # progress of the negotiation session between 0 and 1 (1 is deadline)
        progress = self.progress.get(time() * 1000)

        utility_threshold = 0.9 if self.strategy == "boulware" else 0.8 if self.strategy == "linear" else 0.7
        return self.profile.getUtility(bid) >= utility_threshold or progress > 0.99
    
    def get_line(start: float, lowest: float) -> tuple[float, float]:
        x1, y1 = start, 20
        x2, y2 = 1.0, lowest

        a = (y2 - y1) / (x2 - x1)
        b = y1 - a * x1

        return a, b

    def find_bid(self) -> Bid:
        all_bids = AllBidsList(self.domain)
        population_size = 20
        generations = 10
        mutation_rate = 0.1

        progress = self.progress.get(time() * 1000)
        start_thresholding = 0.8
        lowest_threshold = 1.2

        if self.sent_bids and (progress > start_thresholding):
            a, b = self.get_line(start_thresholding, lowest_threshold)
            threshold_percentage = a*progress + b
            threshold = max(self.score_bid(bid) for bid in self.sent_bids) * threshold_percentage
        else:
            threshold = None

        # Initialize population with more diverse bids
        population = [all_bids.get(randint(0, all_bids.size() - 1)) for _ in range(population_size)]
        for _ in range(generations):
            if threshold is not None:
                population = sorted((bid for bid in population if self.score_bid(bid) < threshold), key=self.score_bid, reverse=True)
            else:
                population = sorted(population, key=self.score_bid, reverse=True)
            new_population = population[:population_size // 2]
            
            # Keep the population diverse with a better crossover and mutation strategy
            while len(new_population) < population_size:
                parent1, parent2 = random.sample(new_population, 2)
                child = self.crossover(parent1, parent2)
                if random.random() < mutation_rate:
                    # Mutate by adjusting values within a bid, not replacing it entirely
                    mutated_bid = self.mutate(child)
                    new_population.append(mutated_bid)
                else:
                    new_population.append(child)

            population = new_population
        return max(population, key=self.score_bid)
    
    def crossover(self, bid1: Bid, bid2: Bid) -> Bid:
        values = bid1.getIssueValues().copy()
        for issue, value in bid2.getIssueValues().items():
            if random.random() > 0.5:
                values[issue] = value
        return Bid(values)

    def mutate(self, bid: Bid) -> Bid:
        # Mutate by randomly changing one of the issue values (not replacing the entire bid)
        issue_to_mutate = random.choice(list(bid.getIssueValues().keys()))
        new_value = bid.getIssueValues()[issue_to_mutate]  # Just a simple mutation strategy
        bid.getIssueValues()[issue_to_mutate] = new_value
        return bid

    def score_bid(self, bid: Bid, alpha: float = 0.95, eps: float = 0.1) -> float:
        """Calculate heuristic score for a bid

        Args:
            bid (Bid): Bid to score
            alpha (float, optional): Trade-off factor between self interested and
                altruistic behaviour. Defaults to 0.95.
            eps (float, optional): Time pressure factor, balances between conceding
                and Boulware behaviour over time. Defaults to 0.1.

        Returns:
            float: score
        """
        progress = self.progress.get(time() * 1000)

        our_utility = float(self.profile.getUtility(bid))

        time_pressure = 1.0 - progress ** (1 / eps)
        score = alpha * time_pressure * our_utility

        if self.opponent_model is not None:
            opponent_utility = self.opponent_model.get_predicted_utility(bid)
            alpha = 0.9 if self.strategy == "boulware" else 0.75 if self.strategy == "linear" else 0.6
            opponent_score = alpha * our_utility + (1 - alpha) * opponent_utility
            score = opponent_score

        return score
