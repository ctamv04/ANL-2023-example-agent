import logging
from random import randint
import random
from time import time
from typing import cast
import json

from geniusweb.actions.Accept import Accept
from geniusweb.actions.Action import Action
from geniusweb.actions.Offer import Offer
from geniusweb.actions.EndNegotiation import EndNegotiation
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


class OurFinalAgent(DefaultParty):
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

        self.last_opponent_utility = None
        self.num_enemy_concessions = 0
        self.previous_utils_oponent_offered = []

        # Starting strategy is boulware:
        self.strategy = "boulware"
        
        # Opponent modelling: Store, for each opponent agent who has walked away from a negotiation, 
        # the average percentage change in opponent utility between their ultimate and penultimate bids.
        self.last_change_if_walk_away = dict()

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

            # Opponent modelling: load data from past negotiations that will be used to adapt the current netgotiation strategy
            self.last_change_if_walk_away = self.load_data()

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
            # Save utilities of recieved bids
            self.previous_utils_oponent_offered.append(float(self.profile.getUtility(bid)))
            # set bid as last received
            self.last_received_bid = bid
            self.adjust_strategy()  # Adjust negotiation strategy based on progress

        # If the opponent has walked away from the negotiation
        if isinstance(action, EndNegotiation):

            if len(self.opponent_model.offers) > 1:

                # Get the last 2 bids made by the opponent before walking away
                ultimate = self.opponent_model.offers[-1]
                penultimate = self.opponent_model.offers[-2]

                if self.other in self.last_change_if_walk_away:

                    # If this specific opponent agent has walked away from a negotiation in the past, update the average based on the percentage change in opponent utility between their ultimate and penultimate bids in this negotiation
                    self.last_change_if_walk_away[self.other]["change"] = (self.last_change_if_walk_away[self.other]["change"] * self.last_change_if_walk_away_sample_size[self.other]["sample_size"] \
                                                                           + (self.opponent_model.get_predicted_utility(ultimate) - self.opponent_model.get_predicted_utility(penultimate)) / self.opponent_model.get_predicted_utility(penultimate)) \
                                                                            / (self.last_change_if_walk_away_sample_size[self.other]["sample_size"] + 1)
                    # Also update the number of times this opponent agent has walked away
                    self.last_change_if_walk_away_sample_size[self.other]["sample_size"] += 1
                else:

                    # If this specific opponent agent has never walked away from a negotiation before, initialize the value with the percentage change in opponent utility between their ultimate and penultimate bids in this negotiation
                    self.last_change_if_walk_away[self.other] = {"change": (self.opponent_model.get_predicted_utility(ultimate) - self.opponent_model.get_predicted_utility(penultimate)) / self.opponent_model.get_predicted_utility(penultimate), "sample_size": 1}
                    
    def track_concessions(self, bid: Bid):
        utility = self.opponent_model.get_predicted_utility(bid)
        if self.last_opponent_utility and utility < self.last_opponent_utility:
            self.num_enemy_concessions += 1
            self.last_opponent_utility = utility
        elif not self.last_opponent_utility:
            self.last_opponent_utility = utility

    def adjust_strategy(self):
        """Adjusts the negotiation strategy based on the progress of the negotiation and the opponent's behavior
            The strategy can be conceder, boulware, or linear
        """

        # Calculate progress based on current time:
        progress = self.progress.get(time() * 1000)

        # If the opponent made very few concessions, switch to conceder:
        if self.num_enemy_concessions / len(self.opponent_model.offers) < 0.15:
            self.strategy = "conceder"
        
        # Otherwise, choose strategy based on progress:
        elif progress < 0.3:
            self.strategy = "boulware"
        elif progress < 0.7:
            self.strategy = "linear"
        else:
            self.strategy = "conceder"

    def my_turn(self):
        """This method is called when it is our turn. It should decide upon an action
        to perform and send this action to the opponent.
        """
        bid = self.find_bid()
        # check if the last received offer is good enough
        if self.accept_condition(self.last_received_bid):
            # if so, accept the offer
            action = Accept(self.me, self.last_received_bid)
        else:
            # if not, find a bid to propose as counter offer
            action = Offer(self.me, bid)

        # send the action
        self.send_action(action)

    def save_data(self):
        """Persist the data used for opponent modelling and dynamic negotiation strategy adaptation into the file 'data.md'
        """
        data = {"last_change_if_walk_away": self.last_change_if_walk_away}
        with open(f"{self.storage_dir}/data.md", "w") as f:
            json.dump(data, f)

    def load_data(self):
        """Load the data from 'data.md' for opponent modelling and dynamic negotiation strategy adaptation
        """
        try:
            with open(f"{self.storage_dir}/data.md", "r") as f:
                data = json.load(f)
                return data.get("last_change_if_walk_away", dict())
        except (FileNotFoundError, json.JSONDecodeError):
            return [], dict()

    def accept_condition(self, bid: Bid) -> bool:
        """Either accept or reject the current bid offered by the opponent based on different heuristics

        Args:
            bid (Bid): Bid to accept/reject

        Returns:
            bool: Acceptance/Rejection decision
        """
        if bid is None:
            return False
        
        # If this agent is known to walk away from negotiations
        if self.other in self.last_change_if_walk_away:

            if len(self.opponent_model.offers) > 1:

                # Get the last 2 bids from the opponent agent
                ultimate = self.opponent_model.offers[-1]
                penultimate = self.opponent_model.offers[-2]

                # If the percentage change in opponent utility between their last 2 bids in the current negotiation is smaller than double the historical average percentage change in opponent utility between their ultimate and penultimate bids before
                # walking away from a negotiation, then immediately accept the current bid to make sure to avoid the worst case scenario of another walk-away
                if (self.opponent_model.get_predicted_utility(ultimate) - self.opponent_model.get_predicted_utility(penultimate)) / self.opponent_model.get_predicted_utility(penultimate) <= self.last_change_if_walk_away[self.other]["change"] * 2:
                    return True

        # progress of the negotiation session between 0 and 1 (1 is deadline)
        progress = self.progress.get(time() * 1000)

        utility_threshold = 0.9 if self.strategy == "boulware" else 0.8 if self.strategy == "linear" else 0.7
        return self.profile.getUtility(bid) >= utility_threshold or progress > 0.99
    
    # Unused tested acceptance criterion
    def accept_combination(self, bid_recieved: Bid, bid_can_propose: Bid) -> bool:
        
        if bid_recieved is None or bid_can_propose is None:
            return False
        
        # progress of the negotiation session between 0 and 1 (1 is deadline)
        progress = self.progress.get(time() * 1000)
         
        # Get the utility of the next bid we can propose and the utility of the bid we got from the opponent
        utility_recieved = float(self.profile.getUtility(bid_recieved))
        utility_proposed = float(self.profile.getUtility(bid_can_propose))

        # Get the for the parameter alpha based on the max / average of all the previouslly offered bids in the window
        n = len(self.previous_utils_oponent_offered)
        window_size = max(1, int((2 * progress - 1) * n))
        center = int(progress * n)
        start = max(0, center - window_size // 2)
        end = min(n, start + window_size)

        a = max(self.previous_utils_oponent_offered[start : end])

        if self.AC_next(utility_recieved, utility_proposed) or (progress > 0.99 and utility_recieved >= a):
            return True

        return False
    
    def AC_next(self, utility_recieved, utility_proposed) -> bool:
        return utility_recieved >= utility_proposed

    def find_bid(self) -> Bid:
        """Finds the best bid with a Genetic Algorithm. 
        Generates a population of bids and evolves them over multiple generations through crossover and mutation,
        selecting the best bid at the end.

            1. Initializes a population of bids.
            2. For 10 generations, the population is sorted based on bid quality, and the top half is kept.
            3. Crossover between pairs of bids generates new bids. Mutations are applied randomly for diversity.
            4. The best bid from the population is returned.

        Returns:
            Bid: The bid that is selected as the best, based on the score_bid method.
        """
        
        all_bids = AllBidsList(self.domain)

        # Establish parameters for GA:
        population_size = 20
        generations = 10
        mutation_rate = 0.1

        # Initialize population of bids:
        population = [all_bids.get(randint(0, all_bids.size() - 1)) for _ in range(population_size)]
        for _ in range(generations):

            # Sort population based on bid score, descendingly:
            population = sorted(population, key=self.score_bid, reverse=True)

            # Only keep the top half (the best half):
            new_population = population[:population_size // 2]
            
            # Generate new bids by crossover and mutation:
            while len(new_population) < population_size:
                # Perform crossover between pairs of bids:
                parent1, parent2 = random.sample(new_population, 2)
                child = self.crossover(parent1, parent2)

                # Do random mutations to increase diversity:
                if random.random() < mutation_rate:
                    mutated_bid = self.mutate(child)
                    new_population.append(mutated_bid)
                else:
                    new_population.append(child)

            population = new_population
        return max(population, key=self.score_bid)
    
    def crossover(self, bid1: Bid, bid2: Bid) -> Bid:
        """Combines the values per issue of the two parents using uniform crossover

        Args:
            bid1 (Bid): One parent bid
            bid2 (Bid): The other parent bid

        Returns:    
            Bid: the child bid
        """

        values = bid1.getIssueValues().copy()

        for issue, value in bid2.getIssueValues().items():
            if random.random() > 0.5: # uniform crossover, so a 50% chance
                values[issue] = value

        return Bid(values)

    def mutate(self, bid: Bid) -> Bid:
        """Mutates a bid by randomly changing the value of one of its issues

        Args:
            bid (Bid): Bid to score

        Returns:    
            Bid: the mutated bid
        """

        issue_values = bid.getIssueValues().copy()

        # Randomly select one of the issues in the bid to mutate:
        issue_to_mutate = random.choice(list(issue_values.keys()))

        values = self.domain.getValues(issue_to_mutate)

        # Remove the value already in the bid from the list:
        values = [v for v in values if v != issue_values[issue_to_mutate]]

        # Randomly choose a new value for the selected issue:
        issue_values[issue_to_mutate] = random.choice(values)

        return Bid(issue_values)

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
            score = alpha * our_utility + (1 - alpha) * opponent_utility

        return score
