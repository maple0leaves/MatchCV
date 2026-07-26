package com.agentrecruit.candidate;

import com.agentrecruit.common.PageResponse;
import com.agentrecruit.security.AuthUser;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CandidateControllerOwnershipTest {

    @Test
    void listAlwaysPassesAuthenticatedUserIdToService() {
        CandidateService service = mock(CandidateService.class);
        when(service.list(27L, 1, 20, null, null))
                .thenReturn(new PageResponse<>(List.of(), 0, 1, 20));
        CandidateController controller = new CandidateController(service);

        controller.list(new AuthUser("27", "user"), 1, 20, null, null);

        verify(service).list(27L, 1, 20, null, null);
    }

    @Test
    void getAlwaysPassesAuthenticatedUserIdToService() {
        CandidateService service = mock(CandidateService.class);
        CandidateController controller = new CandidateController(service);

        controller.get(new AuthUser("27", "user"), 99L);

        verify(service).get(27L, 99L);
    }
}
